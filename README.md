# Hardened Grafana Alloy for Linux

A default [Grafana Alloy](https://grafana.com/docs/alloy/) install on Linux ships **2,000+ series per host** — most of them metrics no dashboard consumes, and cost you'll pay for indefinitely. This repo is a prebuilt, production-ready Alloy config that ships exactly what the [Node Exporter Full dashboard (ID 1860)](https://grafana.com/grafana/dashboards/1860-node-exporter-full/) needs. Defense-in-depth cardinality protection keeps a typical cloud VM around **400–600 series** with no panels missing.

## Pick Your Deployment Path

| Path | When to use | Guide |
|------|-------------|-------|
| **Direct Deployment** | The hardened `config.alloy` lives on each host. You manage config updates via your existing tooling (Ansible, Chef, Puppet, cloud-init, manual). | [docs/direct-deployment.md](docs/direct-deployment.md) |
| **Fleet Management** | A minimal bootstrap config (`fleet-config.alloy`) lives on each host. You build and push the real collection pipelines centrally via Grafana Cloud Fleet Management. | [docs/fleet-management.md](docs/fleet-management.md) |

Both paths need the same five environment variables. See **[docs/env-vars.md](docs/env-vars.md)** for the canonical reference and how to set them (systemd env file, drop-in override, verification commands).

## What's in the box

```
config.alloy                  # Hardened Alloy config (River syntax)
fleet-config.alloy            # Minimal bootstrap for Fleet Management
config-otel.yaml              # Hardened OTEL Collector config (YAML)
ALLOY-VS-OTEL.md              # When to use Alloy vs vanilla OTEL — honest comparison
examples/blackbox.alloy       # Self-contained pipeline pattern (blackbox exporter)

docs/
  direct-deployment.md        # Path 1 end-to-end guide
  fleet-management.md         # Path 2 end-to-end guide
  env-vars.md                 # Canonical reference for all 5 env vars

k8s-monitoring/
  values-hardened.yaml        # Hardened values for k8s-monitoring-helm chart
  values-test.yaml            # Test overrides for local k3d validation

.env.example                  # Credential template (copy to .env for local testing)
Makefile                      # lint, test-tier1, test-tier2, clean

scripts/
  patch_config_for_test.py    # Rewrites config.alloy for Docker test env
  patch_otel_config_for_test.py  # Rewrites config-otel.yaml for Docker test env

tests/
  shared/
    assertions.py             # Reusable Prometheus query helpers
    metrics_allowlist.py      # Parses allow-list from config.alloy
  tier1/                      # Alloy Docker tests (CI)
  tier1-otel/                 # OTEL Collector Docker tests
  tier2/                      # Alloy GCP VM tests (cross-distro)
  tier2-otel/                 # OTEL Collector GCP VM tests

.github/workflows/test.yml    # CI: lint + Tier 1 on every push/PR; weekly scheduled run against latest Alloy
```

## Cardinality protection

The config uses a 4-layer defense-in-depth approach:

| Layer | What it does | Example |
|-------|-------------|---------|
| **1. Allow-list** | Only ~208 dashboard-required metric names pass through | `node_xfs_*` never leaves the host |
| **2. Pattern block** | Drops high-churn label values (UUIDs, container paths, virtual NICs) | `device="veth3a7f..."` dropped |
| **3. Label tagging** | Metrics missing required labels get `quality_warning="missing_required_labels"` — visible for triage, not silently lost | Query `{quality_warning=~".+"}` to find them |
| **4. Value limits** | Truncates extremely long label values | Mountpoints capped at 100 chars |

**Typical series budget:** 400–600 per cloud VM (Alloy), 100–300 per VM (OTEL Collector).

## Systemd monitoring

Systemd is filtered to ~15 essential services to avoid the cardinality explosion that comes from monitoring all ~150 units across 5 states. The default set covers:

- **Remote access:** sshd
- **Scheduling:** cron/crond
- **Time sync:** chronyd, systemd-timesyncd
- **Logging:** systemd-journald
- **DNS:** systemd-resolved
- **Sessions:** systemd-logind, dbus
- **Monitoring:** alloy
- **Containers:** docker, containerd, kubelet
- **Firewall:** firewalld, ufw

To add your own services, edit the `unit_include` regex in the `systemd` block:

```
systemd {
    unit_include = "(...|nginx\\.service|postgresql\\.service|my-app\\.service)"
}
```

## OTEL Collector config (`config-otel.yaml`)

A YAML-native equivalent using standard OpenTelemetry Collector components. Runs on **vanilla `otel/opentelemetry-collector-contrib`** — no Alloy required. Same cardinality protection philosophy, fewer Linux-specific metrics (no systemd, journal, conntrack, PSI).

See [ALLOY-VS-OTEL.md](ALLOY-VS-OTEL.md) for a detailed comparison of when to use which.

```bash
make test-tier1-otel   # Docker tests against vanilla otelcol-contrib
```

## Kubernetes monitoring (`k8s-monitoring/`)

Hardened `values.yaml` for the [Grafana k8s-monitoring-helm](https://github.com/grafana/k8s-monitoring-helm) chart. Enables OTLP ingestion on ports 4317/4318 with cardinality protection against rogue applications:

- Default allow-lists ON for all Prometheus metric sources
- OTLP metric filters drop `go_*`, `process.*`, `rpc.*` at ingestion
- High-churn resource attributes stripped before export
- Health check spans dropped
- Attribute values truncated
- Memory limiter and batch sizing on all collectors

```bash
helm install k8s-monitoring grafana/k8s-monitoring \
  -f k8s-monitoring/values-hardened.yaml \
  --set "destinations[0].auth.password=YOUR_API_KEY"
```

Tested on k3d: **1,635 series / 175 metric names** on a 2-node cluster.

## Testing

### Prerequisites

- Docker Desktop (Tier 1)
- Python 3.10+ with pytest (Tier 1)
- GCP project + `gcloud` auth + Terraform (Tier 2)

### Tier 1 — Docker (fast, runs in CI)

Validates config logic: allow-list correctness, cardinality protection, label tagging, metric budget.

```bash
make test-tier1    # or just: make test
```

Runs 33 tests in ~2 minutes. Uses Docker Compose with Prometheus, Alloy, and a synthetic metrics fixture server.

### Tier 2 — GCP VMs (thorough, cross-distro)

Validates real-world collector behavior that can't be tested in Docker: systemd, PSI, hwmon, real disk/NIC devices, journal logs.

```bash
cd tests/tier2/terraform
cp terraform.tfvars.example terraform.tfvars  # edit with your GCP project
terraform init && terraform apply

cd ../../..
make test-tier2

# Tear down when done
cd tests/tier2/terraform && terraform destroy
```

Tests across 5 distros: Ubuntu 22.04, Debian 12, Rocky 9, CentOS Stream 9, SUSE 15.

### OTEL Tier 1 — Docker (vanilla otelcol-contrib)

Proves `config-otel.yaml` runs on a vanilla OTEL Collector with no Alloy dependency.

```bash
make test-tier1-otel
```

Runs 12 tests. Uses `otel/opentelemetry-collector-contrib:latest`.

### Linting

```bash
make lint          # validates config.alloy syntax
```

## Linux compatibility

Tested on:

| Distro | Version | Notes |
|--------|---------|-------|
| Ubuntu | 20.04+ | Full support |
| Debian | 11+ | Full support |
| RHEL/Rocky | 8+ | PSI may be unavailable on older kernels |
| CentOS Stream | 9 | PSI may be unavailable |
| SUSE (SLES) | 15+ | PSI may be unavailable |
| Amazon Linux | 2023 | Supported; test separately on AWS |

PSI (Pressure Stall Information) metrics require kernel 4.20+ with PSI enabled. On distros where PSI is unavailable, those metrics are simply absent — no errors.

## Customizing

### Adding metrics to the allow-list

Edit the `join([...], "|")` block in `config.alloy` under Layer 1. Add the metric name as a string:

```
"your_custom_metric_name",
```

### Adjusting cardinality rules

Layer 2 rules (pattern blocks) are in the `prometheus.relabel` block. Each rule has a comment explaining what it drops and why.

### Changing the scrape interval

Default is 60s. Edit the `scrape_interval` in the `prometheus.scrape` block. Lower intervals increase series churn and network usage.

## License

See [LICENSE](LICENSE) for details.
