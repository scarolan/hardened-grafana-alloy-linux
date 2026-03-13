"""Reusable Prometheus query and assertion helpers for both test tiers."""

import time
import requests


def query_prometheus(base_url, promql):
    """Execute an instant PromQL query and return the result vector."""
    resp = requests.get(
        f"{base_url}/api/v1/query",
        params={"query": promql},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    assert data["status"] == "success", f"PromQL query failed: {data}"
    return data["data"]["result"]


def get_all_metric_names(base_url, job="integrations/node_exporter"):
    """Return the set of metric names present for a given job."""
    results = query_prometheus(base_url, f'{{job="{job}"}}')
    return {r["metric"]["__name__"] for r in results if "__name__" in r["metric"]}


def get_label_values(base_url, label):
    """Return all values for a given label via the labels API."""
    resp = requests.get(f"{base_url}/api/v1/label/{label}/values", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    assert data["status"] == "success"
    return set(data["data"])


def assert_metric_exists(base_url, metric_name, job="integrations/node_exporter"):
    """Assert that a metric name exists in Prometheus for the given job."""
    results = query_prometheus(base_url, f'{metric_name}{{job="{job}"}}')
    assert len(results) > 0, f"Metric {metric_name} not found for job={job}"


def assert_metric_absent(base_url, metric_name, job="integrations/node_exporter"):
    """Assert that a metric name does NOT exist in Prometheus."""
    results = query_prometheus(base_url, f'{metric_name}{{job="{job}"}}')
    assert len(results) == 0, (
        f"Metric {metric_name} should be absent but found {len(results)} series"
    )


def assert_label_present(base_url, metric_name, label_name, job="integrations/node_exporter"):
    """Assert that all series of a metric have a specific label."""
    results = query_prometheus(base_url, f'{metric_name}{{job="{job}"}}')
    assert len(results) > 0, f"No series found for {metric_name}"
    for r in results:
        assert label_name in r["metric"], (
            f"{metric_name} series missing label '{label_name}': {r['metric']}"
        )


def assert_label_value(base_url, metric_name, label_name, expected_value, job="integrations/node_exporter"):
    """Assert that at least one series of a metric has a label with the expected value."""
    results = query_prometheus(
        base_url, f'{metric_name}{{job="{job}",{label_name}="{expected_value}"}}'
    )
    assert len(results) > 0, (
        f"No {metric_name} series with {label_name}={expected_value}"
    )


def assert_no_label(base_url, metric_name, label_name, job="integrations/node_exporter"):
    """Assert that NO series of a metric have a specific label."""
    results = query_prometheus(base_url, f'{metric_name}{{job="{job}"}}')
    for r in results:
        assert label_name not in r["metric"], (
            f"{metric_name} should not have label '{label_name}' but found: {r['metric']}"
        )


def assert_series_count_in_range(base_url, job, min_count, max_count):
    """Assert total series count for a job is within expected bounds."""
    results = query_prometheus(base_url, f'count({{job="{job}"}})')
    assert len(results) == 1, f"Expected one result from count(), got {len(results)}"
    count = int(float(results[0]["value"][1]))
    assert min_count <= count <= max_count, (
        f"Series count {count} outside expected range [{min_count}, {max_count}]"
    )


def wait_for_prometheus(base_url, timeout=120, interval=5):
    """Block until Prometheus is reachable and has scraped data."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            results = query_prometheus(base_url, "up")
            if len(results) > 0:
                return True
        except (requests.ConnectionError, requests.Timeout, AssertionError):
            pass
        time.sleep(interval)
    raise TimeoutError(f"Prometheus at {base_url} not ready after {timeout}s")


def wait_for_metric(base_url, metric_name, timeout=120, interval=5):
    """Block until a specific metric appears in Prometheus."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            results = query_prometheus(base_url, metric_name)
            if len(results) > 0:
                return True
        except (requests.ConnectionError, requests.Timeout, AssertionError):
            pass
        time.sleep(interval)
    raise TimeoutError(f"Metric {metric_name} not found after {timeout}s")
