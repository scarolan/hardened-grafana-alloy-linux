output "vm_ips" {
  description = "Map of distro name to external IP address"
  value = {
    for k, v in google_compute_instance.alloy_test : k => v.network_interface[0].access_config[0].nat_ip
  }
}

output "vm_details" {
  description = "Full VM details for the test runner"
  value = {
    for k, v in google_compute_instance.alloy_test : k => {
      ip            = v.network_interface[0].access_config[0].nat_ip
      name          = v.name
      zone          = v.zone
      xfail_metrics = var.distros[k].xfail_metrics
      min_series    = var.distros[k].min_series
      max_series    = var.distros[k].max_series
    }
  }
}

output "ssh_user" {
  value = var.ssh_user
}
