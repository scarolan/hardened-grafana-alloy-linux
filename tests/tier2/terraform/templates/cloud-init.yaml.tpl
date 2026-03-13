#cloud-config

write_files:
  # Alloy configuration (production config, patched for local Prometheus)
  - path: /etc/alloy/config.alloy
    permissions: "0644"
    content: |
      ${indent(6, replace(config_alloy, "sys.env(\"GRAFANA_METRICS_URL\")", "\"http://localhost:9090/api/v1/write\""))}

  # Minimal Prometheus config (remote-write receiver only)
  - path: /etc/prometheus/prometheus.yml
    permissions: "0644"
    content: |
      global:
        scrape_interval: 15s

  # Alloy environment file
  - path: /etc/default/alloy
    permissions: "0644"
    content: |
      GCLOUD_RW_API_KEY=not-used-local-test
      GRAFANA_METRICS_URL=http://localhost:9090/api/v1/write
      GRAFANA_METRICS_USERNAME=not-used
      GRAFANA_LOGS_URL=http://localhost:3100/loki/api/v1/push
      GRAFANA_LOGS_USERNAME=not-used

  # Alloy systemd override to load env file
  - path: /etc/systemd/system/alloy.service.d/override.conf
    permissions: "0644"
    content: |
      [Service]
      EnvironmentFile=/etc/default/alloy

  # Install script (handles multi-distro package managers)
  - path: /opt/setup.sh
    permissions: "0755"
    content: |
      #!/bin/bash
      set -euo pipefail
      export DEBIAN_FRONTEND=noninteractive

      echo "=== Distro: ${distro_key} ==="
      echo "=== Installing Grafana Alloy and Prometheus ==="

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

      # Detect package manager and install
      if command -v apt-get &>/dev/null; then
        install_grafana_repo_apt
        apt-get install -y -qq alloy prometheus
      elif command -v dnf &>/dev/null; then
        install_grafana_repo_rpm
        dnf install -y alloy
        # Prometheus from EPEL or Fedora repos
        dnf install -y prometheus || dnf install -y golang-github-prometheus
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

      # If Prometheus wasn't available as a package, download the binary
      if ! command -v prometheus &>/dev/null && ! command -v promtool &>/dev/null; then
        echo "=== Installing Prometheus from binary release ==="
        PROM_VERSION="2.51.0"
        ARCH=$(uname -m)
        case $ARCH in
          x86_64) ARCH="amd64" ;;
          aarch64) ARCH="arm64" ;;
        esac
        cd /tmp
        wget -q "https://github.com/prometheus/prometheus/releases/download/v$${PROM_VERSION}/prometheus-$${PROM_VERSION}.linux-$${ARCH}.tar.gz"
        tar xzf "prometheus-$${PROM_VERSION}.linux-$${ARCH}.tar.gz"
        cp "prometheus-$${PROM_VERSION}.linux-$${ARCH}/prometheus" /usr/local/bin/
        cp "prometheus-$${PROM_VERSION}.linux-$${ARCH}/promtool" /usr/local/bin/

        # Create systemd unit for Prometheus
        cat > /etc/systemd/system/prometheus.service <<'SVC'
      [Unit]
      Description=Prometheus
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
      fi

      # Ensure Prometheus starts with remote-write receiver enabled
      # Override the default service if installed from package
      if [ -f /usr/lib/systemd/system/prometheus.service ] && ! [ -f /etc/systemd/system/prometheus.service ]; then
        mkdir -p /etc/systemd/system/prometheus.service.d
        cat > /etc/systemd/system/prometheus.service.d/override.conf <<'OVR'
      [Service]
      ExecStart=
      ExecStart=/usr/bin/prometheus \
        --config.file=/etc/prometheus/prometheus.yml \
        --web.enable-remote-write-receiver \
        --storage.tsdb.retention.time=1h
      OVR
      fi

      systemctl daemon-reload
      systemctl enable --now prometheus
      systemctl enable --now alloy

      echo "=== Setup complete ==="

runcmd:
  - bash /opt/setup.sh
  - touch /tmp/cloud-init-done
