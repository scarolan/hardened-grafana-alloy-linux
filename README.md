# Hardened Grafana Alloy for Linux

A production-ready, hardened [Grafana Alloy](https://grafana.com/docs/alloy/) configuration for Linux monitoring with defense-in-depth cardinality protection.

Ships every metric required by the [Node Exporter Full](https://grafana.com/grafana/dashboards/1860-node-exporter-full/) dashboard (ID 1860) while keeping series counts lean and predictable.

## What's in the box

```
config.alloy                  # Hardened Alloy config (River syntax)
config-otel.yaml              # Hardened OTEL Collector config (YAML)
ALLOY-VS-OTEL.md             # When to use which — honest comparison
.env.example                  # Credential template (copy to .env)
Makefile                      # lint, test-tier1, test-tier2, clean

k8s-monitoring/
  values-hardened.yaml        # Hardened values for k8s-monitoring-helm chart
  values-test.yaml            # Test overrides for local k3d validation

scripts/
  patch_config_for_test.py    # Rewrites config.alloy for Docker test env
  patch_otel_config_for_test.py  # Rewrites config-otel.yaml for Docker test env

tests/
  shared/
    assertions.py             # Reusable Prometheus query helpers
    metrics_allowlist.py      # Parses allow-list from config.alloy
  tier1/                      # Alloy Docker tests (CI)
    docker-compose.yml
    test_runner.py            # 33 pytest cases
    fixtures/                 # Synthetic metrics for cardinality tests
  tier1-otel/                 # OTEL Collector Docker tests
    docker-compose.yml        # Uses vanilla otel/opentelemetry-collector-contrib
    test_runner.py            # 12 pytest cases
  tier2/                      # Alloy GCP VM tests (cross-distro)
    terraform/
    test_runner.py            # 55 pytest cases
  tier2-otel/                 # OTEL Collector GCP VM tests
    terraform/
    test_runner.py            # 55 pytest cases

.github/workflows/test.yml   # CI: lint + Tier 1 on every push/PR
```

## Cardinality protection

The config uses a 4-layer defense-in-depth approach:

| Layer | What it does | Example |
|-------|-------------|---------|
| **1. Allow-list** | Only ~208 dashboard-required metric names pass through | `node_xfs_*` never leaves the host |
| **2. Pattern block** | Drops high-churn label values (UUIDs, container paths, virtual NICs) | `device="veth3a7f..."` dropped |
| **3. Label tagging** | Metrics missing required labels get `quality_warning="missing_required_labels"` — visible for triage, not silently lost | Query `{quality_warning=~".+"}` to find them |
| **4. Value limits** | Truncates extremely long label values | Mountpoints capped at 100 chars |

**Typical series budget:** 400-600 per cloud VM (Alloy), 100-300 per VM (OTEL Collector).

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

## Quick start

### 1. Set up credentials

```bash
cp .env.example .env
# Edit .env with your Grafana Cloud credentials
```

### 2. Deploy

Copy `config.alloy` and your `.env` to the target host:

```bash
# Install Alloy (Debian/Ubuntu)
apt-get install -y gpg wget
wget -qO- https://apt.grafana.com/gpg.key | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
  > /etc/apt/sources.list.d/grafana.list
apt-get update && apt-get install -y alloy

# Install Alloy (RHEL/Rocky/CentOS)
cat > /etc/yum.repos.d/grafana.repo <<'EOF'
[grafana]
name=grafana
baseurl=https://rpm.grafana.com
repo_gpgcheck=1
enabled=1
gpgcheck=1
gpgkey=https://rpm.grafana.com/gpg.key
sslverify=1
sslcacert=/etc/pki/tls/certs/ca-bundle.crt
EOF
dnf install -y alloy

# Deploy config
cp config.alloy /etc/alloy/config.alloy

# Set credentials in the Alloy env file
# Debian/Ubuntu: /etc/default/alloy
# RHEL/Rocky/CentOS/SUSE: /etc/sysconfig/alloy
cat >> /etc/default/alloy <<'EOF'
GCLOUD_RW_API_KEY=your-api-key
GRAFANA_METRICS_URL=https://prometheus-prod-XX-prod-us-east-0.grafana.net/api/prom/push
GRAFANA_METRICS_USERNAME=123456
GRAFANA_LOGS_URL=https://logs-prod-XX.grafana.net/loki/api/v1/push
GRAFANA_LOGS_USERNAME=654321
EOF

# Start
systemctl enable --now alloy
```

### 3. Verify

Open the [Node Exporter Full](https://grafana.com/grafana/dashboards/1860-node-exporter-full/) dashboard in Grafana. All panels should populate.

Check for data-quality issues:

```promql
{quality_warning=~".+"}
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

## Self-monitoring (optional)

Fleet management via `remotecfg` is disabled by default. It adds ~216 self-monitoring series (`job="integrations/alloy"`). To enable, uncomment the `remotecfg` block in `config.alloy` and set the fleet credentials in your `.env`.

> **⚠️ Fleet Management gotcha: remote_write endpoints are not shared**
>
> The `prometheus.remote_write` and `loki.write` blocks in `fleet-config.alloy` are **not reachable** from pipelines you push via Fleet Management. Each FM pipeline is wrapped in a sealed `declare` module, and components inside a module can't reference components in the parent scope.
>
> **You must include a `prometheus.remote_write` and/or `loki.write` block inside every FM pipeline** that ships data. Use `sys.env()` for credentials — set `GCLOUD_RW_API_KEY`, `GRAFANA_METRICS_URL`, `GRAFANA_METRICS_USERNAME`, `GRAFANA_LOGS_URL`, and `GRAFANA_LOGS_USERNAME` once per host so you don't have to hardcode values in every pipeline.
>
> See `examples/blackbox.alloy` for a complete self-contained pipeline pattern you can copy.

### Why env vars instead of hardcoding values into pipelines?

Two reasons, and neither adds meaningful operational burden:

1. **Secrets don't belong in the Fleet Management UI.** Pipelines you push via FM are stored in Grafana Cloud's config store and visible to anyone with FM access. Hardcoding your API key there means a Grafana Cloud user with the right role can read it, and it ends up in every pipeline export, backup, and screenshot. Keeping it in `sys.env()` means the secret lives on the host — rotated through your existing secret management, never echoed back in the UI.

2. **You already have to set `GCLOUD_RW_API_KEY` on the host.** Alloy can't connect to Fleet Management without it. Since you're already setting one env var, adding four more (URLs + usernames) is seconds of extra work via the same systemd unit override or `/etc/default/alloy` file. It's not "yet another file to manage" — it's four more lines in the mechanism you already use.

The URLs and usernames aren't secret, but keeping them next to the password means rotations and stack migrations are atomic: change the host env, restart Alloy, done. No need to re-edit N pipelines in the FM UI to point at a new stack.

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
# Set up infrastructure
cd tests/tier2/terraform
cp terraform.tfvars.example terraform.tfvars  # edit with your GCP project
terraform init && terraform apply

# Run tests
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
