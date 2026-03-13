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
  description = "GCE machine type (e2-small is sufficient for monitoring tests)"
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
  description = "Map of distro name to GCP image. Override to test a subset."
  type = map(object({
    image_project = string
    image_family  = string
    # Metrics that may not exist on this distro (marked xfail in tests)
    xfail_metrics = optional(list(string), [])
    # Expected series count range
    min_series = optional(number, 300)
    max_series = optional(number, 900)
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
    sles15 = {
      image_project = "suse-cloud"
      image_family  = "sles-15"
      xfail_metrics = ["node_pressure_cpu_waiting_seconds_total"]
    }
    # Amazon Linux 2023 is not natively available on GCP.
    # Options:
    #   a) Import an AMI via gcloud compute images import
    #   b) Test it separately on AWS
    #   c) Use a community image
    # Uncomment and set image_project/family if you have an imported image:
    # amzn2023 = {
    #   image_project = "your-project"
    #   image_family  = "amazon-linux-2023"
    # }
  }
}
