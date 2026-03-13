"""Tier 2 tests: GCP VM-based validation across Linux distributions.

These tests validate real-world collector behavior that cannot be tested
in Docker: systemd, PSI, hwmon, real disk/NIC devices, journal logs.

Prerequisites:
  - Terraform applied: cd tests/tier2/terraform && terraform apply
  - VMs are running with Alloy + Prometheus
  - gcloud auth login (uses gcloud compute ssh for access)

Run via: make test-tier2
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
    get_all_metric_names,
    assert_metric_exists,
    assert_series_count_in_range,
    wait_for_metric,
)
from metrics_allowlist import ALLOWLIST

# ---------------------------------------------------------------------------
# Configuration from Terraform outputs
# ---------------------------------------------------------------------------

TERRAFORM_DIR = os.path.join(os.path.dirname(__file__), "terraform")


def get_terraform_output():
    """Read VM details from Terraform output."""
    result = subprocess.run(
        ["terraform", "output", "-json", "vm_details"],
        cwd=TERRAFORM_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# SSH via gcloud compute ssh (handles OS Login and key management)
# ---------------------------------------------------------------------------

def ssh_command(vm_name, zone, command, timeout=30):
    """Execute a command on a GCP VM via gcloud compute ssh."""
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


def wait_for_cloud_init(vm_name, zone, timeout=300):
    """Wait for cloud-init to complete on a VM."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            code, out, _ = ssh_command(
                vm_name, zone,
                "test -f /tmp/cloud-init-done && echo ready",
                timeout=15,
            )
            if code == 0 and "ready" in out:
                return True
        except (subprocess.TimeoutExpired, Exception):
            pass
        time.sleep(15)
    raise TimeoutError(f"cloud-init not done on {vm_name} after {timeout}s")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def vm_details():
    """Load VM details from Terraform and wait for all VMs to be ready."""
    details = get_terraform_output()

    # Wait for cloud-init on all VMs
    for distro, info in details.items():
        name = info["name"]
        zone = info["zone"]
        ip = info["ip"]
        print(f"\nWaiting for cloud-init on {distro} ({name})...")
        wait_for_cloud_init(name, zone)
        print(f"  {distro} ready, waiting for first scrape...")
        # Wait for Prometheus to have data
        prom_url = f"http://{ip}:9090"
        wait_for_metric(prom_url, "node_load1", timeout=180, interval=10)
        print(f"  {distro} scrape confirmed.")

    return details


def distro_ids():
    """Generate test IDs from Terraform state (for parametrize)."""
    try:
        details = get_terraform_output()
        return list(details.keys())
    except Exception:
        return ["ubuntu2204", "rocky9", "debian12", "sles15"]


# ---------------------------------------------------------------------------
# Tests parametrized per distro
# ---------------------------------------------------------------------------

class TestServiceHealth:
    """Verify Alloy and Prometheus are running on each VM."""

    @pytest.mark.parametrize("distro", distro_ids())
    def test_alloy_running(self, vm_details, distro):
        info = vm_details[distro]
        code, out, _ = ssh_command(
            info["name"], info["zone"], "systemctl is-active alloy"
        )
        assert "active" in out, f"Alloy not active on {distro}: {out}"

    @pytest.mark.parametrize("distro", distro_ids())
    def test_prometheus_running(self, vm_details, distro):
        info = vm_details[distro]
        code, out, _ = ssh_command(
            info["name"], info["zone"], "systemctl is-active prometheus"
        )
        assert "active" in out, f"Prometheus not active on {distro}: {out}"


class TestCollectorHealth:
    """Verify all enabled collectors report success."""

    @pytest.mark.parametrize("distro", distro_ids())
    def test_all_collectors_healthy(self, vm_details, distro):
        ip = vm_details[distro]["ip"]
        prom_url = f"http://{ip}:9090"

        results = query_prometheus(prom_url, "node_scrape_collector_success == 0")
        failed = [r["metric"].get("collector", "unknown") for r in results]
        assert len(failed) == 0, (
            f"Failed collectors on {distro}: {failed}"
        )


class TestRealCollectors:
    """Test collectors that require real VMs (not available in Docker)."""

    @pytest.mark.parametrize("distro", distro_ids())
    def test_systemd_metrics(self, vm_details, distro):
        """systemd unit state metrics must exist on real systemd hosts."""
        ip = vm_details[distro]["ip"]
        prom_url = f"http://{ip}:9090"

        results = query_prometheus(prom_url, "node_systemd_unit_state")
        assert len(results) > 0, f"No node_systemd_unit_state on {distro}"

    @pytest.mark.parametrize("distro", distro_ids())
    def test_psi_metrics(self, vm_details, distro):
        """PSI metrics require kernel 4.20+ with PSI enabled."""
        info = vm_details[distro]
        ip = info["ip"]
        prom_url = f"http://{ip}:9090"

        xfail = info.get("xfail_metrics", [])
        if "node_pressure_cpu_waiting_seconds_total" in xfail:
            pytest.xfail(f"PSI known-unsupported on {distro}")

        results = query_prometheus(prom_url, "node_pressure_cpu_waiting_seconds_total")
        assert len(results) > 0, f"No PSI metrics on {distro}"

    @pytest.mark.parametrize("distro", distro_ids())
    def test_real_disk_device(self, vm_details, distro):
        """Disk metrics should reference real devices (sda, nvme0n1), not just loop."""
        ip = vm_details[distro]["ip"]
        prom_url = f"http://{ip}:9090"

        results = query_prometheus(prom_url, "node_disk_read_bytes_total")
        devices = {r["metric"].get("device", "") for r in results}
        real_devices = {d for d in devices if not d.startswith("loop")}
        assert len(real_devices) > 0, (
            f"No real disk devices on {distro}, only found: {devices}"
        )

    @pytest.mark.parametrize("distro", distro_ids())
    def test_real_network_interface(self, vm_details, distro):
        """Network metrics should have real NICs (eth0, ens*), not lo/veth."""
        ip = vm_details[distro]["ip"]
        prom_url = f"http://{ip}:9090"

        results = query_prometheus(prom_url, "node_network_receive_bytes_total")
        devices = {r["metric"].get("device", "") for r in results}

        # Should NOT have virtual interfaces (cardinality rules)
        virtual = {d for d in devices if d.startswith(("lo", "veth", "docker", "cali"))}
        assert len(virtual) == 0, (
            f"Virtual interfaces not filtered on {distro}: {virtual}"
        )

        # Should HAVE at least one real interface
        real = {d for d in devices if d.startswith(("eth", "ens", "enp"))}
        assert len(real) > 0, (
            f"No real network interfaces on {distro}, found: {devices}"
        )

    @pytest.mark.parametrize("distro", distro_ids())
    def test_hwmon_metrics(self, vm_details, distro):
        """hwmon metrics may not exist on cloud VMs (no physical sensors)."""
        ip = vm_details[distro]["ip"]
        prom_url = f"http://{ip}:9090"

        results = query_prometheus(prom_url, "node_hwmon_temp_celsius")
        if len(results) == 0:
            pytest.xfail(f"No hwmon sensors available on {distro} (expected for cloud VMs)")


class TestMetricBudget:
    """Verify series counts are within expected bounds per distro."""

    @pytest.mark.parametrize("distro", distro_ids())
    def test_series_count(self, vm_details, distro):
        info = vm_details[distro]
        ip = info["ip"]
        prom_url = f"http://{ip}:9090"

        min_s = info.get("min_series", 300)
        max_s = info.get("max_series", 900)

        assert_series_count_in_range(
            prom_url, "integrations/node_exporter", min_s, max_s
        )


class TestAllowListCompliance:
    """Verify only allow-listed metrics are present on real VMs."""

    @pytest.mark.parametrize("distro", distro_ids())
    def test_no_metrics_outside_allowlist(self, vm_details, distro):
        ip = vm_details[distro]["ip"]
        prom_url = f"http://{ip}:9090"

        present = get_all_metric_names(prom_url)
        unexpected = present - ALLOWLIST
        assert not unexpected, (
            f"Metrics outside allow-list on {distro}: {sorted(unexpected)}"
        )


class TestDashboard1860Coverage:
    """Verify critical dashboard 1860 metrics exist on real hosts."""

    # Core metrics that MUST exist on every Linux distro
    CRITICAL_METRICS = [
        "up",
        "node_boot_time_seconds",
        "node_cpu_seconds_total",
        "node_load1",
        "node_load5",
        "node_load15",
        "node_memory_MemTotal_bytes",
        "node_memory_MemFree_bytes",
        "node_memory_MemAvailable_bytes",
        "node_filesystem_size_bytes",
        "node_filesystem_avail_bytes",
        "node_disk_read_bytes_total",
        "node_disk_written_bytes_total",
        "node_network_receive_bytes_total",
        "node_network_transmit_bytes_total",
        "node_context_switches_total",
        "node_forks_total",
        "node_uname_info",
        "node_filefd_allocated",
        "node_vmstat_pgfault",
        "node_vmstat_pgmajfault",
        "node_netstat_Tcp_CurrEstab",
        "node_sockstat_TCP_inuse",
        "node_systemd_units",
    ]

    @pytest.mark.parametrize("distro", distro_ids())
    def test_critical_metrics_present(self, vm_details, distro):
        ip = vm_details[distro]["ip"]
        prom_url = f"http://{ip}:9090"

        present = get_all_metric_names(prom_url)
        missing = [m for m in self.CRITICAL_METRICS if m not in present]
        assert not missing, (
            f"Dashboard 1860 critical metrics missing on {distro}: {missing}"
        )
