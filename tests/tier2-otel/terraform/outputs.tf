output "ssh_user" {
  value = var.ssh_user
}

output "vm_details" {
  value = {
    for k, v in google_compute_instance.otel_test : k => {
      name       = v.name
      ip         = v.network_interface[0].access_config[0].nat_ip
      zone       = v.zone
      min_series = var.distros[k].min_series
      max_series = var.distros[k].max_series
    }
  }
}

output "vm_ips" {
  value = {
    for k, v in google_compute_instance.otel_test : k => v.network_interface[0].access_config[0].nat_ip
  }
}
