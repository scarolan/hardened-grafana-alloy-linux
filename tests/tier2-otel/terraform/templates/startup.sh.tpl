#!/bin/bash
# GCP startup script for OTEL Collector test VM (${distro_key})
# Installs vanilla otelcol-contrib + Prometheus, deploys config, starts services.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "=== OTEL Collector test setup: ${distro_key} ==="

# -----------------------------------------------------------------------
# Step 1: Install otelcol-contrib from binary release
# -----------------------------------------------------------------------
echo "=== Step 1: Install otelcol-contrib ==="
OTEL_VERSION="0.145.0"
ARCH=$(uname -m)
case $ARCH in
  x86_64) ARCH="amd64" ;;
  aarch64) ARCH="arm64" ;;
esac

cd /tmp
OTEL_URL="https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v$${OTEL_VERSION}/otelcol-contrib_$${OTEL_VERSION}_linux_$${ARCH}.tar.gz"
if command -v wget &>/dev/null; then
  wget -q "$OTEL_URL" -O otelcol-contrib.tar.gz
elif command -v curl &>/dev/null; then
  curl -sSL "$OTEL_URL" -o otelcol-contrib.tar.gz
else
  # Install curl first
  if command -v apt-get &>/dev/null; then
    apt-get update -qq && apt-get install -y -qq curl
  elif command -v dnf &>/dev/null; then
    dnf install -y curl
  elif command -v zypper &>/dev/null; then
    zypper install -y curl
  fi
  curl -sSL "$OTEL_URL" -o otelcol-contrib.tar.gz
fi
tar xzf otelcol-contrib.tar.gz
cp otelcol-contrib /usr/local/bin/
chmod +x /usr/local/bin/otelcol-contrib

# -----------------------------------------------------------------------
# Step 2: Install Prometheus from binary
# -----------------------------------------------------------------------
echo "=== Step 2: Install Prometheus ==="
PROM_VERSION="2.51.0"
PROM_URL="https://github.com/prometheus/prometheus/releases/download/v$${PROM_VERSION}/prometheus-$${PROM_VERSION}.linux-$${ARCH}.tar.gz"
if command -v wget &>/dev/null; then
  wget -q "$PROM_URL" -O prometheus.tar.gz
else
  curl -sSL "$PROM_URL" -o prometheus.tar.gz
fi
tar xzf prometheus.tar.gz
cp "prometheus-$${PROM_VERSION}.linux-$${ARCH}/prometheus" /usr/local/bin/
cp "prometheus-$${PROM_VERSION}.linux-$${ARCH}/promtool" /usr/local/bin/

# -----------------------------------------------------------------------
# Step 3: Deploy configs
# -----------------------------------------------------------------------
echo "=== Step 3: Deploy configs ==="

mkdir -p /etc/otelcol-contrib
cat > /etc/otelcol-contrib/config.yaml <<'OTEL_CONFIG'
${config_otel}
OTEL_CONFIG

mkdir -p /etc/prometheus
cat > /etc/prometheus/prometheus.yml <<'PROM_CONFIG'
global:
  scrape_interval: 15s
PROM_CONFIG

# -----------------------------------------------------------------------
# Step 4: Create systemd units
# -----------------------------------------------------------------------
echo "=== Step 4: Configure services ==="

cat > /etc/systemd/system/otelcol-contrib.service <<'SVC'
[Unit]
Description=OpenTelemetry Collector Contrib
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/otelcol-contrib --config=/etc/otelcol-contrib/config.yaml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVC

cat > /etc/systemd/system/prometheus.service <<'SVC'
[Unit]
Description=Prometheus (test)
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --web.enable-remote-write-receiver \
  --storage.tsdb.retention.time=1h \
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
systemctl enable --now otelcol-contrib

sleep 5
systemctl is-active prometheus && echo "Prometheus: OK" || echo "Prometheus: FAILED"
systemctl is-active otelcol-contrib && echo "otelcol-contrib: OK" || echo "otelcol-contrib: FAILED"

echo "=== Setup complete ==="
touch /tmp/cloud-init-done
