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
    # cloud-init user-data
    user-data = templatefile("${path.module}/templates/cloud-init.yaml.tpl", {
      config_alloy = local.config_alloy
      distro_key   = each.key
    })
  }

  # Allow cloud-init to finish
  metadata_startup_script = <<-EOT
    #!/bin/bash
    # Wait for cloud-init to complete, then signal readiness
    cloud-init status --wait || true
    touch /tmp/cloud-init-done
  EOT

  labels = {
    purpose = "alloy-test"
    distro  = each.key
  }

  # Auto-delete after 2 hours as a safety net
  scheduling {
    automatic_restart = false
    preemptible       = true
  }
}
