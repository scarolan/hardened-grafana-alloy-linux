#!/usr/bin/env python3
"""Patch config.alloy for test environments.

Rewrites the production config to:
- Point remote_write at a local Prometheus (http://prometheus:9090/api/v1/write)
- Stub out Loki (comment out the journal module since it won't work in Docker)
- Remove auth requirements
- Inject a synthetic metrics scrape job for cardinality rule testing
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "config.alloy"
DST = REPO_ROOT / "tests" / "tier1" / "config.alloy.test"


def patch():
    config = SRC.read_text()

    # --- Replace Prometheus remote_write endpoint ---
    # Replace sys.env("GRAFANA_METRICS_URL") with local Prometheus
    config = config.replace(
        'url = sys.env("GRAFANA_METRICS_URL")',
        'url = "http://prometheus:9090/api/v1/write"',
    )

    # Replace metrics auth block with dummy values
    config = re.sub(
        r'(endpoint\s*\{[^}]*url\s*=\s*"http://prometheus:9090/api/v1/write"\s*\n)'
        r'\s*basic_auth\s*\{[^}]*\}\s*\n',
        r'\1',
        config,
    )

    # --- Replace Loki endpoint with a blackhole (Alloy won't crash, just won't send) ---
    config = config.replace(
        'url = sys.env("GRAFANA_LOGS_URL")',
        'url = "http://localhost:3100/loki/api/v1/push"',
    )
    # Remove Loki auth
    config = re.sub(
        r'(url\s*=\s*"http://localhost:3100/loki/api/v1/push"\s*\n)'
        r'\s*basic_auth\s*\{[^}]*\}\s*\n',
        r'\1',
        config,
    )

    # --- Add synthetic metrics scrape job for cardinality testing ---
    # This scrapes a fixture server that serves metrics designed to trigger
    # the cardinality protection and label validation rules.
    synthetic_block = '''
// ---------------------------------------------------------------------------
// TEST ONLY: Synthetic metrics scrape for cardinality rule validation
// ---------------------------------------------------------------------------
discovery.relabel "synthetic_test" {
\ttargets = [{
\t\t__address__ = "fixture-server:9999",
\t}]
\trule {
\t\ttarget_label = "instance"
\t\treplacement  = constants.hostname
\t}
\trule {
\t\ttarget_label = "job"
\t\treplacement  = "integrations/node_exporter"
\t}
}

prometheus.scrape "synthetic_test" {
\ttargets         = discovery.relabel.synthetic_test.output
\tforward_to      = [prometheus.relabel.integrations_node_exporter.receiver]
\tscrape_interval = "15s"
}
'''
    # Append the synthetic block before the log collection section
    config += "\n" + synthetic_block

    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(config)
    print(f"Patched config written to {DST}")


if __name__ == "__main__":
    patch()
