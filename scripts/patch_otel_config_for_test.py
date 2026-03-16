#!/usr/bin/env python3
"""Patch config-otel.yaml for Docker test environments.

Rewrites the production OTEL config to:
- Point prometheusremotewrite at a local Prometheus (http://prometheus:9090/api/v1/write)
- Remove auth extensions (no credentials in test)
- Disable the logs pipeline (no Loki in test)
- Use /hostfs root_path for containerized hostmetrics collection
"""

import yaml
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "config-otel.yaml"
DST = REPO_ROOT / "tests" / "tier1-otel" / "config-otel.test.yaml"


def patch():
    # Read as raw text first to strip ${env:...} vars that break yaml.safe_load
    raw = SRC.read_text()

    # Replace env var references with dummy values for parsing
    import re
    raw = re.sub(r'\$\{env:([^}]+)\}', r'dummy-\1', raw)

    config = yaml.safe_load(raw)

    # --- Remove auth extensions ---
    extensions = config.get("extensions", {})
    extensions.pop("basicauth/grafana", None)
    extensions.pop("basicauth/loki", None)

    # --- Point prometheusremotewrite at local Prometheus ---
    exporters = config.get("exporters", {})
    exporters["prometheusremotewrite/grafana"] = {
        "endpoint": "http://prometheus:9090/api/v1/write",
        "resource_to_telemetry_conversion": {"enabled": True},
    }

    # --- Remove loki exporter (no Loki in test) ---
    exporters.pop("otlphttp/loki", None)

    # --- Configure hostmetrics for container environment ---
    receivers = config.get("receivers", {})
    if "hostmetrics" in receivers:
        receivers["hostmetrics"]["root_path"] = "/hostfs"

    # --- Remove filelog receiver (no syslog in container) ---
    receivers.pop("filelog/syslog", None)

    # --- Update service pipelines ---
    service = config.get("service", {})

    # Remove auth from extensions list
    svc_extensions = service.get("extensions", [])
    svc_extensions = [e for e in svc_extensions if not e.startswith("basicauth/")]
    service["extensions"] = svc_extensions

    # Remove logs pipeline
    pipelines = service.get("pipelines", {})
    pipelines.pop("logs", None)

    # Clean metrics pipeline — remove auth-dependent processors
    if "metrics" in pipelines:
        metrics_pipeline = pipelines["metrics"]
        # Remove filelog from receivers if somehow present
        if "receivers" in metrics_pipeline:
            metrics_pipeline["receivers"] = [
                r for r in metrics_pipeline["receivers"]
                if r != "filelog/syslog"
            ]
        # Keep only the prometheusremotewrite exporter
        metrics_pipeline["exporters"] = ["prometheusremotewrite/grafana"]

    config["service"] = service

    DST.parent.mkdir(parents=True, exist_ok=True)

    with open(DST, "w") as f:
        f.write("# AUTO-GENERATED — do not edit. See scripts/patch_otel_config_for_test.py\n")
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # Fix null scrapers → empty dicts (OTEL expects {} not null)
    content = DST.read_text()
    import re as re2
    content = re2.sub(r'^(\s+(?:cpu|memory|load|paging|processes)):\s*null\s*$',
                      r'\1: {}', content, flags=re2.MULTILINE)
    DST.write_text(content)

    print(f"Patched OTEL config written to {DST}")


if __name__ == "__main__":
    patch()
