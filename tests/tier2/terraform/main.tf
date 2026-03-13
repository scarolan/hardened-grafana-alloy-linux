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

# Read the production config to embed in cloud-init
locals {
  config_alloy = file("${path.module}/../../../config.alloy")
  ssh_public_key = file(pathexpand(var.ssh_public_key_path))
}

# Firewall rule: allow SSH from anywhere (test-only; scope to CI runner IP in production)
resource "google_compute_firewall" "allow_ssh" {
  name    = "alloy-test-allow-ssh"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["alloy-test"]
}

# Firewall rule: allow Prometheus query from test runner (test-only)
resource "google_compute_firewall" "allow_prometheus" {
  name    = "alloy-test-allow-prometheus"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["9090"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["alloy-test"]
}

# One VM per distro
resource "google_compute_instance" "alloy_test" {
  for_each = var.distros

  name         = "alloy-test-${each.key}"
  machine_type = var.machine_type
  zone         = var.zone
  tags         = ["alloy-test"]

  boot_disk {
    initialize_params {
      image = "${each.value.image_project}/${each.value.image_family}"
      size  = 20
    }
  }

  network_interface {
    network = "default"
    access_config {} # ephemeral public IP
  }

  metadata = {
    ssh-keys = "${var.ssh_user}:${local.ssh_public_key}"
  }

  # Startup script: installs Alloy + Prometheus, deploys config, starts services.
  # Uses metadata_startup_script (works on ALL GCP images, no cloud-init needed).
  metadata_startup_script = templatefile("${path.module}/templates/cloud-init.yaml.tpl", {
    config_alloy = local.config_alloy
    distro_key   = each.key
  })

  labels = {
    purpose = "alloy-test"
    distro  = each.key
  }

  # Use standard instances to avoid preemption during test runs.
  # VMs are destroyed by `make clean` or `terraform destroy` after tests.
  scheduling {
    automatic_restart = true
    preemptible       = false
  }
}
