variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for VM instances"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP zone for VM instances"
  type        = string
  default     = "us-central1-a"
}

variable "machine_type" {
  description = "GCE machine type"
  type        = string
  default     = "e2-small"
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key for test runner access"
  type        = string
  default     = "~/.ssh/id_rsa.pub"
}

variable "ssh_user" {
  description = "SSH username for test runner"
  type        = string
  default     = "testrunner"
}

variable "distros" {
  description = "Map of distro name to GCP image."
  type = map(object({
    image_project = string
    image_family  = string
    min_series    = optional(number, 50)
    max_series    = optional(number, 500)
  }))
  default = {
    ubuntu2204 = {
      image_project = "ubuntu-os-cloud"
      image_family  = "ubuntu-2204-lts"
    }
    rocky9 = {
      image_project = "rocky-linux-cloud"
      image_family  = "rocky-linux-9"
    }
    debian12 = {
      image_project = "debian-cloud"
      image_family  = "debian-12"
    }
    centos9 = {
      image_project = "centos-cloud"
      image_family  = "centos-stream-9"
    }
    sles15 = {
      image_project = "suse-cloud"
      image_family  = "sles-15"
    }
  }
}
