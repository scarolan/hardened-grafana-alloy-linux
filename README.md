# Hardened Grafana Alloy for Linux

A production-ready, hardened [Grafana Alloy](https://grafana.com/docs/alloy/) configuration for Linux monitoring with defense-in-depth cardinality protection.

Ships every metric required by the [Node Exporter Full](https://grafana.com/grafana/dashboards/1860-node-exporter-full/) dashboard (ID 1860) while keeping series counts lean and predictable.

## What's in the box

```
config.alloy                  # Production config — the main deliverable
.env.example                  # Credential template (copy to .env)
Makefile                      # lint, test-tier1, test-tier2, clean
scripts/
  patch_config_for_test.py    # Rewrites config.alloy for Docker test env
tests/
  shared/
    assertions.py             # Reusable Prometheus query helpers
    metrics_allowlist.py      # Parses allow-list from config.alloy
  tier1/                      # Fast Docker-based tests (CI)
    docker-compose.yml
    test_runner.py            # 33 pytest cases
    fixtures/                 # Synthetic metrics for cardinality tests
  tier2/                      # GCP VM-based tests (cross-distro)
    terraform/                # Provisions VMs across 5 Linux distros
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

**Typical series budget:** 400-600 per cloud VM.

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

## Self-monitoring (optional)

Fleet management via `remotecfg` is disabled by default. It adds ~216 self-monitoring series (`job="integrations/alloy"`). To enable, uncomment the `remotecfg` block in `config.alloy` and set the fleet credentials in your `.env`.

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
