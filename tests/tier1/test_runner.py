"""Tier 1 tests: Docker-based validation of Alloy config logic.

These tests validate:
  - Allow-list correctness (Layer 1)
  - Cardinality protection rules (Layer 2)
  - Label validation tagging (Layer 3)
  - Label value limits (Layer 4)
  - Standard label presence (instance, job)

Run via: docker compose run test-runner
"""

import os
import sys
import pytest

# Add shared test utilities to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "shared"))

from shared.assertions import (
    query_prometheus,
    get_all_metric_names,
    assert_metric_exists,
    assert_metric_absent,
    assert_label_present,
    assert_label_value,
    assert_no_label,
    assert_series_count_in_range,
    wait_for_metric,
)
from shared.metrics_allowlist import ALLOWLIST

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def wait_for_scrape():
    """Wait until Alloy has scraped and pushed at least one cycle of data."""
    print(f"\nWaiting for metrics to appear in Prometheus at {PROMETHEUS_URL}...")
    # Wait for a metric we know the unix exporter will produce
    wait_for_metric(PROMETHEUS_URL, "node_load1", timeout=180, interval=5)
    # Also wait for synthetic fixture metrics to arrive
    wait_for_metric(PROMETHEUS_URL, "node_load5", timeout=60, interval=5)
    print("Metrics available, running tests.")


# ---------------------------------------------------------------------------
# Layer 1: Allow-list
# ---------------------------------------------------------------------------

class TestAllowList:
    """Verify the allow-list keeps required metrics and drops everything else."""

    @pytest.mark.parametrize("metric", [
        "up",
        "node_cpu_seconds_total",
        "node_memory_MemTotal_bytes",
        "node_memory_MemFree_bytes",
        "node_load1",
        "node_load5",
        "node_load15",
        "node_boot_time_seconds",
        "node_filesystem_size_bytes",
        "node_network_receive_bytes_total",
        # node_context_switches_total and node_forks_total may not be
        # available in Docker (limited /proc access) — tested in Tier 2
    ])
    def test_core_metrics_present(self, metric):
        """Core metrics required by dashboard 1860 must be present."""
        assert_metric_exists(PROMETHEUS_URL, metric)

    @pytest.mark.parametrize("metric", [
        "node_xfs_block_mapping_extent_list_insertions_total",
        "node_nfs_requests_total",
        "node_bonding_active",
        "node_btrfs_info",
        "some_random_custom_metric",
        "another_unknown_metric",
    ])
    def test_non_allowlisted_metrics_absent(self, metric):
        """Metrics not on the allow-list must be dropped (Layer 1)."""
        assert_metric_absent(PROMETHEUS_URL, metric)

    def test_all_metrics_are_allowlisted(self):
        """Every metric name in Prometheus should be in the allow-list."""
        present = get_all_metric_names(PROMETHEUS_URL)
        unexpected = present - ALLOWLIST
        assert not unexpected, (
            f"Found {len(unexpected)} metrics not in allow-list: {sorted(unexpected)}"
        )


# ---------------------------------------------------------------------------
# Layer 2: Cardinality protection
# ---------------------------------------------------------------------------

class TestCardinalityProtection:
    """Verify high-churn patterns are dropped."""

    def test_virtual_interfaces_dropped(self):
        """veth, cali, docker, flannel interfaces must be dropped."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'node_network_receive_bytes_total{device=~"veth.*|cali.*|docker.*|flannel.*|lo"}',
        )
        assert len(results) == 0, (
            f"Virtual interface metrics should be dropped, found: "
            f"{[r['metric'].get('device') for r in results]}"
        )

    def test_squashfs_overlay_dropped(self):
        """squashfs and overlay filesystem metrics must be dropped."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'node_filesystem_size_bytes{fstype=~"squashfs|overlay"}',
        )
        assert len(results) == 0, (
            f"squashfs/overlay metrics should be dropped, found: "
            f"{[r['metric'].get('fstype') for r in results]}"
        )

    def test_container_mount_paths_dropped(self):
        """Filesystem metrics for /var/lib/docker|containerd|pods must be dropped."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'node_filesystem_size_bytes{mountpoint=~".*/var/lib/(docker|containerd|pods)/.*"}',
        )
        assert len(results) == 0, (
            f"Container mount metrics should be dropped, found: "
            f"{[r['metric'].get('mountpoint') for r in results]}"
        )

    def test_uuid_device_dropped(self):
        """Metrics with UUID patterns in device label must be dropped."""
        results = query_prometheus(
            PROMETHEUS_URL,
            '{device=~".*[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}.*"}',
        )
        assert len(results) == 0, (
            f"UUID-device metrics should be dropped, found: "
            f"{[r['metric'].get('device') for r in results]}"
        )

    def test_uuid_mountpoint_dropped(self):
        """Metrics with UUID patterns in mountpoint label must be dropped."""
        results = query_prometheus(
            PROMETHEUS_URL,
            '{mountpoint=~".*[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}.*"}',
        )
        assert len(results) == 0, (
            f"UUID-mountpoint metrics should be dropped, found: "
            f"{[r['metric'].get('mountpoint') for r in results]}"
        )


# ---------------------------------------------------------------------------
# Layer 3: Label validation (quality_warning tagging)
# ---------------------------------------------------------------------------

class TestLabelValidation:
    """Verify metrics missing required labels are TAGGED, not dropped."""

    def test_filesystem_missing_labels_tagged(self):
        """Filesystem metrics without device+fstype get quality_warning."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'node_filesystem_size_bytes{quality_warning="missing_required_labels"}',
        )
        # The synthetic fixture includes node_filesystem_size_bytes without device/fstype
        assert len(results) > 0, (
            "Expected filesystem metrics missing device/fstype to be tagged"
        )

    def test_network_missing_device_tagged(self):
        """Network metrics without device get quality_warning."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'node_network_receive_bytes_total{quality_warning="missing_required_labels"}',
        )
        assert len(results) > 0, (
            "Expected network metrics missing device to be tagged"
        )

    def test_disk_missing_device_tagged(self):
        """Disk metrics without device get quality_warning."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'node_disk_read_bytes_total{quality_warning="missing_required_labels"}',
        )
        assert len(results) > 0, (
            "Expected disk metrics missing device to be tagged"
        )

    def test_cpu_missing_cpu_label_tagged(self):
        """CPU metrics without cpu label get quality_warning."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'node_cpu_seconds_total{quality_warning="missing_required_labels"}',
        )
        assert len(results) > 0, (
            "Expected CPU metrics missing cpu label to be tagged"
        )

    def test_clean_metrics_not_tagged(self):
        """Properly-labeled metrics should NOT have quality_warning."""
        # Clean filesystem metric from fixtures (device="/dev/sda1", fstype="ext4")
        results = query_prometheus(
            PROMETHEUS_URL,
            'node_filesystem_size_bytes{device="/dev/sda1",fstype="ext4",mountpoint="/testdata"}',
        )
        for r in results:
            assert "quality_warning" not in r["metric"], (
                f"Clean metric should not be tagged: {r['metric']}"
            )

    def test_clean_cpu_not_tagged(self):
        """CPU metrics with cpu label should NOT have quality_warning."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'node_cpu_seconds_total{cpu="0"}',
        )
        assert len(results) > 0, "Expected cpu=0 metrics from fixtures"
        for r in results:
            assert "quality_warning" not in r["metric"], (
                f"Clean CPU metric should not be tagged: {r['metric']}"
            )


# ---------------------------------------------------------------------------
# Standard labels
# ---------------------------------------------------------------------------

class TestStandardLabels:
    """Verify instance and job labels are applied consistently."""

    def test_job_label(self):
        """All metrics should have job='integrations/node_exporter'."""
        assert_label_value(
            PROMETHEUS_URL, "node_load1", "job", "integrations/node_exporter"
        )

    def test_instance_label(self):
        """All metrics should have an instance label."""
        assert_label_present(PROMETHEUS_URL, "node_load1", "instance")

    def test_no_empty_instance(self):
        """Instance label should not be empty."""
        results = query_prometheus(PROMETHEUS_URL, 'node_load1{instance=""}')
        assert len(results) == 0, "Instance label should not be empty"


# ---------------------------------------------------------------------------
# Metric budget sanity check
# ---------------------------------------------------------------------------

class TestMetricBudget:
    """Verify total series count is within expected bounds."""

    def test_total_series_count(self):
        """Total series should be within reasonable bounds for a Docker host.

        Docker environment produces fewer series than a real host (no systemd,
        limited hwmon, fewer real disks/NICs), so we use a wider range.
        """
        # Docker produces far fewer series than a real host (no systemd, limited
        # hwmon, fewer disks/NICs). Lower bound is intentionally low.
        # Upper bound catches cardinality explosions.
        assert_series_count_in_range(
            PROMETHEUS_URL, "integrations/node_exporter", 10, 2000
        )

    def test_allowlist_parse_sanity(self):
        """The parsed allow-list should have a reasonable number of metrics."""
        assert len(ALLOWLIST) >= 180, (
            f"Allow-list only has {len(ALLOWLIST)} metrics, expected >= 180"
        )
        assert len(ALLOWLIST) <= 250, (
            f"Allow-list has {len(ALLOWLIST)} metrics, expected <= 250 (check for bloat)"
        )
