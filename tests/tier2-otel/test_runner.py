"""Tier 2 OTEL tests: GCP VM-based validation of vanilla otelcol-contrib across Linux distros.

Validates real-world hostmetrics collection on actual VMs — things that
can't be tested in Docker: real NICs, real disks, full /proc access.

Prerequisites:
  - Terraform applied: cd tests/tier2-otel/terraform && terraform apply
  - VMs running otelcol-contrib + Prometheus
  - gcloud auth login

Run via: make test-tier2-otel
"""

import json
import os
import subprocess
import sys
import time

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
from assertions import (
    query_prometheus,
    assert_series_count_in_range,
    wait_for_metric,
)

TERRAFORM_DIR = os.path.join(os.path.dirname(__file__), "terraform")
JOB = "integrations/host_metrics"


def get_terraform_output():
    result = subprocess.run(
        ["terraform", "output", "-json", "vm_details"],
        cwd=TERRAFORM_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def ssh_command(vm_name, zone, command, timeout=30):
    result = subprocess.run(
        [
            "gcloud", "compute", "ssh", vm_name,
            f"--zone={zone}",
            "--quiet",
            f"--command={command}",
        ],
        capture_output=True,
        text=True,
        timeout=timeout + 10,
    )
    return result.returncode, result.stdout, result.stderr


def wait_for_cloud_init(vm_name, zone, timeout=600):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            code, out, _ = ssh_command(vm_name, zone,
                "test -f /tmp/cloud-init-done && echo ready", timeout=15)
            if code == 0 and "ready" in out:
                return True
        except (subprocess.TimeoutExpired, Exception):
            pass
        time.sleep(15)
    raise TimeoutError(f"cloud-init not done on {vm_name} after {timeout}s")


def get_otel_metric_names(prom_url):
    """Get all system_* metric names from Prometheus."""
    results = query_prometheus(prom_url, f'{{job="{JOB}"}}')
    return {r["metric"]["__name__"] for r in results if "__name__" in r["metric"]}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def vm_details():
    details = get_terraform_output()
    for distro, info in details.items():
        name = info["name"]
        zone = info["zone"]
        ip = info["ip"]
        print(f"\nWaiting for cloud-init on {distro} ({name})...")
        wait_for_cloud_init(name, zone)
        print(f"  {distro} ready, waiting for metrics...")
        prom_url = f"http://{ip}:9090"
        # Wait for a representative OTel metric
        wait_for_metric(prom_url, "system_cpu_time_seconds_total", timeout=180, interval=10)
        print(f"  {distro} metrics confirmed.")
    return details


def distro_ids():
    try:
        return list(get_terraform_output().keys())
    except Exception:
        return ["ubuntu2204", "rocky9", "debian12", "centos9", "sles15"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestServiceHealth:
    """Verify otelcol-contrib and Prometheus are running."""

    @pytest.mark.parametrize("distro", distro_ids())
    def test_otelcol_running(self, vm_details, distro):
        info = vm_details[distro]
        code, out, _ = ssh_command(
            info["name"], info["zone"], "systemctl is-active otelcol-contrib"
        )
        assert "active" in out, f"otelcol-contrib not active on {distro}: {out}"

    @pytest.mark.parametrize("distro", distro_ids())
    def test_prometheus_running(self, vm_details, distro):
        info = vm_details[distro]
        code, out, _ = ssh_command(
            info["name"], info["zone"], "systemctl is-active prometheus"
        )
        assert "active" in out, f"Prometheus not active on {distro}: {out}"


class TestCoreMetrics:
    """Verify hostmetrics receiver produces expected metric families."""

    EXPECTED_PREFIXES = [
        "system_cpu",
        "system_memory",
        "system_disk",
        "system_filesystem",
        "system_network",
        "system_paging",
        "system_processes",
    ]

    @pytest.mark.parametrize("distro", distro_ids())
    def test_all_metric_families_present(self, vm_details, distro):
        ip = vm_details[distro]["ip"]
        prom_url = f"http://{ip}:9090"
        names = get_otel_metric_names(prom_url)
        for prefix in self.EXPECTED_PREFIXES:
            matching = [n for n in names if n.startswith(prefix)]
            assert len(matching) > 0, (
                f"No metrics with prefix '{prefix}' on {distro}. "
                f"Available: {sorted(names)}"
            )


class TestRealCollectors:
    """Test real-VM behavior: real disks, real NICs."""

    @pytest.mark.parametrize("distro", distro_ids())
    def test_real_disk_device(self, vm_details, distro):
        """Disk metrics should reference real devices (sda, nvme0n1)."""
        ip = vm_details[distro]["ip"]
        prom_url = f"http://{ip}:9090"
        results = query_prometheus(prom_url, f'system_disk_io_bytes_total{{job="{JOB}"}}')
        devices = {r["metric"].get("device", "") for r in results}
        real = {d for d in devices if not d.startswith(("loop", "dm-", "ram"))}
        assert len(real) > 0, f"No real disk devices on {distro}, found: {devices}"

    @pytest.mark.parametrize("distro", distro_ids())
    def test_real_network_interface(self, vm_details, distro):
        """Network metrics should have real NICs, not lo/veth."""
        ip = vm_details[distro]["ip"]
        prom_url = f"http://{ip}:9090"
        results = query_prometheus(prom_url, f'system_network_io_bytes_total{{job="{JOB}"}}')
        if not results:
            results = query_prometheus(prom_url, f'{{__name__=~"system_network.*",job="{JOB}"}}')
        devices = {r["metric"].get("device", "") for r in results}

        virtual = {d for d in devices if d in ("lo",) or d.startswith(("veth", "docker", "cali"))}
        assert len(virtual) == 0, f"Virtual interfaces not filtered on {distro}: {virtual}"

        real = {d for d in devices if d.startswith(("eth", "ens", "enp"))}
        assert len(real) > 0, f"No real NICs on {distro}, found: {devices}"

    @pytest.mark.parametrize("distro", distro_ids())
    def test_filesystem_excludes_virtual(self, vm_details, distro):
        """Filesystem metrics should not include tmpfs, devtmpfs, etc."""
        ip = vm_details[distro]["ip"]
        prom_url = f"http://{ip}:9090"
        results = query_prometheus(prom_url, f'system_filesystem_usage_bytes{{job="{JOB}"}}')
        types = {r["metric"].get("type", "") for r in results}
        virtual = types & {"tmpfs", "devtmpfs", "overlay", "squashfs"}
        assert len(virtual) == 0, f"Virtual fstypes not excluded on {distro}: {virtual}"


class TestCardinalityProtection:
    """Verify filter processor is working on real VMs."""

    @pytest.mark.parametrize("distro", distro_ids())
    def test_no_uuid_devices(self, vm_details, distro):
        ip = vm_details[distro]["ip"]
        prom_url = f"http://{ip}:9090"
        results = query_prometheus(
            prom_url,
            '{device=~".*[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}.*"}'
        )
        assert len(results) == 0, f"UUID device labels found on {distro}"


class TestStandardLabels:
    """Verify resource labels are applied correctly."""

    @pytest.mark.parametrize("distro", distro_ids())
    def test_job_label(self, vm_details, distro):
        ip = vm_details[distro]["ip"]
        prom_url = f"http://{ip}:9090"
        results = query_prometheus(prom_url, f'{{job="{JOB}"}}')
        assert len(results) > 0, f"No metrics with job={JOB} on {distro}"

    @pytest.mark.parametrize("distro", distro_ids())
    def test_instance_label(self, vm_details, distro):
        ip = vm_details[distro]["ip"]
        prom_url = f"http://{ip}:9090"
        results = query_prometheus(prom_url, f'system_cpu_time_seconds_total{{job="{JOB}"}}')
        assert len(results) > 0
        for r in results[:5]:
            assert "instance" in r["metric"], (
                f"Missing instance label on {distro}: {r['metric']}"
            )


class TestMetricBudget:
    """Verify series count is within expected bounds."""

    @pytest.mark.parametrize("distro", distro_ids())
    def test_series_count(self, vm_details, distro):
        info = vm_details[distro]
        ip = info["ip"]
        prom_url = f"http://{ip}:9090"
        min_s = info.get("min_series", 50)
        max_s = info.get("max_series", 500)
        assert_series_count_in_range(prom_url, JOB, min_s, max_s)


class TestPortability:
    """Verify this is vanilla otelcol-contrib, not Alloy."""

    @pytest.mark.parametrize("distro", distro_ids())
    def test_binary_is_otelcol(self, vm_details, distro):
        """The running binary should be otelcol-contrib, not alloy."""
        info = vm_details[distro]
        code, out, _ = ssh_command(
            info["name"], info["zone"],
            "/usr/local/bin/otelcol-contrib --version"
        )
        assert "otelcol-contrib" in out, f"Not otelcol-contrib on {distro}: {out}"
