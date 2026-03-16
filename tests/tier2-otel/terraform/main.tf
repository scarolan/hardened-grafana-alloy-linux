terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

locals {
  ssh_public_key = file(pathexpand(var.ssh_public_key_path))

  # Build a test-ready OTEL config: local Prometheus, no auth, no logs pipeline
  config_otel = <<-YAML
extensions:
  health_check:
    endpoint: "0.0.0.0:13133"

receivers:
  hostmetrics:
    collection_interval: 60s
    scrapers:
      cpu: {}
      memory: {}
      load: {}
      disk:
        exclude:
          devices:
            - "^loop\\d+$"
            - "^dm-\\d+$"
            - "^ram\\d+$"
          match_type: regexp
      filesystem:
        exclude_fs_types:
          fs_types:
            - autofs
            - binfmt_misc
            - bpf
            - cgroup
            - cgroup2
            - configfs
            - debugfs
            - devpts
            - devtmpfs
            - tmpfs
            - fusectl
            - hugetlbfs
            - iso9660
            - mqueue
            - nsfs
            - overlay
            - proc
            - procfs
            - pstore
            - rpc_pipefs
            - securityfs
            - selinuxfs
            - squashfs
            - sysfs
            - tracefs
          match_type: strict
        exclude_mount_points:
          mount_points:
            - "^/(dev|proc|sys|run/credentials/.+|var/lib/docker/.+)($|/)"
          match_type: regexp
      network:
        exclude:
          interfaces:
            - "^lo$"
            - "^docker.*"
            - "^veth.*"
            - "^cali.*"
            - "^flannel\\.\\d+"
            - "^[a-f0-9]{15}$"
          match_type: regexp
      paging: {}
      processes: {}

processors:
  batch:
    timeout: 5s
    send_batch_size: 1024
  memory_limiter:
    check_interval: 5s
    limit_mib: 256
    spike_limit_mib: 64
  resourcedetection:
    detectors: [system]
    system:
      hostname_sources: ["os"]
      resource_attributes:
        host.name:
          enabled: true
        os.type:
          enabled: true
  resource/labels:
    attributes:
      - key: job
        value: "integrations/host_metrics"
        action: upsert
      - key: instance
        from_attribute: host.name
        action: upsert
  filter/cardinality:
    error_mode: ignore
    metrics:
      datapoint:
        - 'IsMatch(attributes["device"], ".*[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}.*")'
        - 'IsMatch(attributes["mountpoint"], ".*/var/lib/(docker|containerd|pods)/.*")'
        - 'IsMatch(attributes["mountpoint"], ".*[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}.*")'
  transform/label_validation:
    error_mode: ignore
    metric_statements:
      - context: datapoint
        conditions:
          - 'IsMatch(metric.name, "^system\\.filesystem\\.")'
        statements:
          - 'set(attributes["quality_warning"], "missing_required_attributes") where attributes["device"] == nil or attributes["type"] == nil'
      - context: datapoint
        conditions:
          - 'IsMatch(metric.name, "^system\\.network\\.")'
        statements:
          - 'set(attributes["quality_warning"], "missing_required_attributes") where attributes["device"] == nil'
      - context: datapoint
        conditions:
          - 'IsMatch(metric.name, "^system\\.disk\\.")'
        statements:
          - 'set(attributes["quality_warning"], "missing_required_attributes") where attributes["device"] == nil'
      - context: datapoint
        conditions:
          - 'IsMatch(metric.name, "^system\\.cpu\\.")'
        statements:
          - 'set(attributes["quality_warning"], "missing_required_attributes") where attributes["cpu"] == nil'
  transform/truncate:
    error_mode: ignore
    metric_statements:
      - context: datapoint
        statements:
          - 'truncate_all(attributes, 100)'

exporters:
  prometheusremotewrite/local:
    endpoint: "http://localhost:9090/api/v1/write"
    resource_to_telemetry_conversion:
      enabled: true

service:
  extensions:
    - health_check
  pipelines:
    metrics:
      receivers:
        - hostmetrics
      processors:
        - memory_limiter
        - resourcedetection
        - resource/labels
        - filter/cardinality
        - transform/label_validation
        - transform/truncate
        - batch
      exporters:
        - prometheusremotewrite/local
  YAML
}

resource "google_compute_firewall" "allow_ssh" {
  name    = "otel-test-allow-ssh"
  network = "default"
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["otel-test"]
}

resource "google_compute_firewall" "allow_prometheus" {
  name    = "otel-test-allow-prometheus"
  network = "default"
  allow {
    protocol = "tcp"
    ports    = ["9090"]
  }
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["otel-test"]
}

resource "google_compute_instance" "otel_test" {
  for_each = var.distros

  name         = "otel-test-${each.key}"
  machine_type = var.machine_type
  zone         = var.zone
  tags         = ["otel-test"]

  boot_disk {
    initialize_params {
      image = "${each.value.image_project}/${each.value.image_family}"
      size  = 20
    }
  }

  network_interface {
    network = "default"
    access_config {}
  }

  metadata = {
    ssh-keys = "${var.ssh_user}:${local.ssh_public_key}"
  }

  metadata_startup_script = templatefile("${path.module}/templates/startup.sh.tpl", {
    config_otel = local.config_otel
    distro_key  = each.key
  })

  labels = {
    purpose = "otel-test"
    distro  = each.key
  }

  scheduling {
    automatic_restart = true
    preemptible       = false
  }
}
