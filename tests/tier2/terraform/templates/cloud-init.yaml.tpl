#!/bin/bash
# GCP startup script for Alloy test VM (${distro_key})
# Uses metadata_startup_script which works on ALL GCP images (no cloud-init required)
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "=== Alloy test setup: ${distro_key} ==="

# -----------------------------------------------------------------------
# Step 1: Install packages
# -----------------------------------------------------------------------
echo "=== Step 1: Install packages ==="

install_grafana_repo_apt() {
  apt-get update -qq
  apt-get install -y -qq gpg wget apt-transport-https software-properties-common
  mkdir -p /etc/apt/keyrings
  wget -qO- https://apt.grafana.com/gpg.key | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg
  echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
    > /etc/apt/sources.list.d/grafana.list
  apt-get update -qq
}

install_grafana_repo_rpm() {
  cat > /etc/yum.repos.d/grafana.repo <<'REPO'
[grafana]
name=grafana
baseurl=https://rpm.grafana.com
repo_gpgcheck=1
enabled=1
gpgcheck=1
gpgkey=https://rpm.grafana.com/gpg.key
sslverify=1
sslcacert=/etc/pki/tls/certs/ca-bundle.crt
REPO
}

install_grafana_repo_zypper() {
  rpm --import https://rpm.grafana.com/gpg.key
  zypper addrepo https://rpm.grafana.com grafana || true
  zypper --gpg-auto-import-keys refresh grafana
}

if command -v apt-get &>/dev/null; then
  install_grafana_repo_apt
  apt-get install -y -qq -o Dpkg::Options::="--force-confnew" alloy prometheus
elif command -v dnf &>/dev/null; then
  install_grafana_repo_rpm
  dnf install -y alloy
  dnf install -y prometheus || dnf install -y golang-github-prometheus || true
elif command -v yum &>/dev/null; then
  install_grafana_repo_rpm
  yum install -y alloy
  yum install -y prometheus || true
elif command -v zypper &>/dev/null; then
  install_grafana_repo_zypper
  zypper install -y alloy
  zypper install -y prometheus || true
else
  echo "ERROR: No supported package manager found"
  exit 1
fi

# -----------------------------------------------------------------------
# Step 2: Install Prometheus from binary if package not available
# -----------------------------------------------------------------------
if ! command -v prometheus &>/dev/null; then
  # Check common package install locations
  PROM_BIN=$(find /usr -name prometheus -type f 2>/dev/null | head -1)
  if [ -z "$PROM_BIN" ]; then
    echo "=== Installing Prometheus from binary release ==="
    PROM_VERSION="2.51.0"
    ARCH=$(uname -m)
    case $ARCH in
      x86_64) ARCH="amd64" ;;
      aarch64) ARCH="arm64" ;;
    esac
    cd /tmp
    PROM_URL="https://github.com/prometheus/prometheus/releases/download/v$${PROM_VERSION}/prometheus-$${PROM_VERSION}.linux-$${ARCH}.tar.gz"
    if command -v wget &>/dev/null; then
      wget -q "$PROM_URL"
    else
      curl -sSLO "$PROM_URL"
    fi
    tar xzf "prometheus-$${PROM_VERSION}.linux-$${ARCH}.tar.gz"
    cp "prometheus-$${PROM_VERSION}.linux-$${ARCH}/prometheus" /usr/local/bin/
    cp "prometheus-$${PROM_VERSION}.linux-$${ARCH}/promtool" /usr/local/bin/
  fi
fi

# -----------------------------------------------------------------------
# Step 3: Deploy configs (AFTER package install to avoid conffile conflicts)
# -----------------------------------------------------------------------
echo "=== Step 3: Deploy configs ==="

# Alloy config
mkdir -p /etc/alloy
cat > /etc/alloy/config.alloy <<'ALLOY_CONFIG'
${config_alloy}
ALLOY_CONFIG

# Alloy environment file — includes vars expected by the config AND
# the $CONFIG_FILE / $CUSTOM_ARGS vars expected by Alloy's systemd unit
cat > /etc/default/alloy <<'ALLOY_ENV'
CONFIG_FILE=/etc/alloy/config.alloy
CUSTOM_ARGS=--stability.level=generally-available
GCLOUD_RW_API_KEY=not-used-local-test
GRAFANA_METRICS_URL=http://localhost:9090/api/v1/write
GRAFANA_METRICS_USERNAME=not-used
GRAFANA_LOGS_URL=http://localhost:3100/loki/api/v1/push
GRAFANA_LOGS_USERNAME=not-used
ALLOY_ENV

# Prometheus config
mkdir -p /etc/prometheus
cat > /etc/prometheus/prometheus.yml <<'PROM_CONFIG'
global:
  scrape_interval: 15s
PROM_CONFIG

# -----------------------------------------------------------------------
# Step 4: Configure Prometheus systemd unit with remote-write receiver
# -----------------------------------------------------------------------
echo "=== Step 4: Configure Prometheus service ==="

PROM_BIN=$(command -v prometheus 2>/dev/null || find /usr /usr/local -name prometheus -type f 2>/dev/null | head -1)

cat > /etc/systemd/system/prometheus.service <<SVC
[Unit]
Description=Prometheus (test)
After=network.target

[Service]
Type=simple
ExecStart=$PROM_BIN \\
  --config.file=/etc/prometheus/prometheus.yml \\
  --web.enable-remote-write-receiver \\
  --storage.tsdb.retention.time=1h \\
  --storage.tsdb.path=/var/lib/prometheus
Restart=always

[Install]
WantedBy=multi-user.target
SVC
mkdir -p /var/lib/prometheus

# -----------------------------------------------------------------------
# Step 5: Start services
# -----------------------------------------------------------------------
echo "=== Step 5: Start services ==="
systemctl daemon-reload
systemctl enable --now prometheus
systemctl enable --now alloy

# Wait and verify
sleep 5
systemctl is-active prometheus && echo "Prometheus: OK" || echo "Prometheus: FAILED"
systemctl is-active alloy && echo "Alloy: OK" || echo "Alloy: FAILED"

echo "=== Setup complete ==="
touch /tmp/cloud-init-done
