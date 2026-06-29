output "resource_group_name" {
  description = "Resource group containing the environment."
  value       = azurerm_resource_group.this.name
}

output "vm_name" {
  description = "Name of the GPU virtual machine."
  value       = azurerm_linux_virtual_machine.this.name
}

output "admin_username" {
  description = "Admin username for SSH."
  value       = var.admin_username
}

output "public_ip_address" {
  description = "Public IP address of the VM."
  value       = azurerm_public_ip.this.ip_address
}

output "ssh_connection_string" {
  description = "Ready-to-use SSH command."
  value       = "ssh ${var.admin_username}@${azurerm_public_ip.this.ip_address}"
}

output "vm_size" {
  description = "VM size / SKU."
  value       = var.vm_size
}

output "location" {
  description = "Azure region."
  value       = var.location
}
