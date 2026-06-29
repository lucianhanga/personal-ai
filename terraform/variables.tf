###############################################################################
# Subscription / identity
#
# SECURITY: Pin the target subscription explicitly so Terraform never silently
# falls back to whatever the az CLI default happens to be. Two similarly-named
# subscriptions exist in different tenants; pinning here prevents deploying to
# the wrong one. Set the value in terraform.tfvars.
###############################################################################

variable "subscription_id" {
  description = "Azure subscription ID that all resources are deployed into. Pinned to avoid relying on the az CLI default subscription."
  type        = string
  default     = ""

  validation {
    condition     = var.subscription_id != ""
    error_message = "subscription_id must be set explicitly (see terraform.tfvars). Refusing to rely on the az CLI default subscription."
  }
}

###############################################################################
# Core placement
###############################################################################

variable "location" {
  description = "Azure region for all resources."
  type        = string
  default     = "westeurope"
}

variable "resource_group_name" {
  description = "Resource group that holds the A100 dev environment."
  type        = string
  default     = "ai-devel-a100-rg"
}

###############################################################################
# Naming (defaults mirror the source ARM template exactly)
###############################################################################

variable "vm_name" {
  description = "Name (and computer name) of the GPU virtual machine."
  type        = string
  default     = "vm-ai-a100-devel"
}

variable "vnet_name" {
  description = "Virtual network name."
  type        = string
  default     = "vm-ai-a100-devel-vnet"
}

variable "subnet_name" {
  description = "Subnet name."
  type        = string
  default     = "default"
}

variable "public_ip_name" {
  description = "Public IP resource name."
  type        = string
  default     = "vm-ai-a100-devel-ip"
}

variable "nic_name" {
  description = "Network interface name (kept identical to the ARM template)."
  type        = string
  default     = "vm-ai-a100-devel678"
}

variable "nsg_name" {
  description = "Network security group name."
  type        = string
  default     = "vm-ai-a100-devel-nsg"
}

###############################################################################
# Networking address space
###############################################################################

variable "vnet_address_space" {
  description = "Address space for the virtual network."
  type        = list(string)
  default     = ["10.0.0.0/16"]
}

variable "subnet_address_prefixes" {
  description = "Address prefixes for the default subnet."
  type        = list(string)
  default     = ["10.0.0.0/24"]
}

###############################################################################
# SSH access control
#
# SECURITY: The original ARM template allowed SSH from "*" (the entire
# internet). That is intentionally NOT the default here. By default we restrict
# SSH to the operator's current public IP, which the provision script can
# auto-detect and pass in. Override explicitly if you need a wider/corporate
# CIDR. Setting this to "*" is strongly discouraged.
###############################################################################

variable "ssh_source_address_prefix" {
  description = "Source CIDR allowed to reach SSH (port 22). Defaults to your current public IP via the provision script. Avoid '*'."
  type        = string
  default     = "127.0.0.1/32"

  validation {
    condition     = var.ssh_source_address_prefix != "*"
    error_message = "Refusing to open SSH to the whole internet ('*'). Provide a specific IP or CIDR (e.g. 203.0.113.10/32)."
  }
}

###############################################################################
# Virtual machine
###############################################################################

variable "vm_size" {
  description = "VM size. Single NVIDIA A100 (NC A100 v4 family)."
  type        = string
  default     = "Standard_NC24ads_A100_v4"
}

variable "admin_username" {
  description = "Admin username for SSH login."
  type        = string
  default     = "azureuser"
}

variable "ssh_public_key_path" {
  description = "Path to the SSH public key used for VM auth. Used when ssh_public_key is empty. Defaults to a dedicated key created once by provision.sh and reused for every VM."
  type        = string
  default     = "~/.ssh/ai-a100-devel.pub"
}

variable "ssh_public_key" {
  description = "Inline SSH public key content. If set, takes precedence over ssh_public_key_path."
  type        = string
  default     = ""
}

variable "os_disk_storage_account_type" {
  description = "Storage account type for the OS disk."
  type        = string
  default     = "Premium_LRS"
}

###############################################################################
# Priority / Spot configuration
###############################################################################

variable "vm_priority" {
  description = "VM purchasing model. 'Spot' draws from Low-Priority quota (cheap, evictable). 'Regular' draws from standard family quota (on-demand, not evictable)."
  type        = string
  default     = "Spot"

  validation {
    condition     = contains(["Spot", "Regular"], var.vm_priority)
    error_message = "vm_priority must be either 'Spot' or 'Regular'."
  }
}

variable "spot_max_bid_price" {
  description = "Max price (USD/hour) for the Spot VM. -1 means pay up to the on-demand price (no eviction on price)."
  type        = number
  default     = -1
}

variable "spot_eviction_policy" {
  description = "Eviction policy for the Spot VM. Deallocate keeps the disk; Delete removes it."
  type        = string
  default     = "Deallocate"

  validation {
    condition     = contains(["Deallocate", "Delete"], var.spot_eviction_policy)
    error_message = "spot_eviction_policy must be either 'Deallocate' or 'Delete'."
  }
}

###############################################################################
# Marketplace image (NVIDIA NGC) + plan
###############################################################################

variable "image_publisher" {
  description = "Marketplace image publisher."
  type        = string
  default     = "nvidia"
}

variable "image_offer" {
  description = "Marketplace image offer / product."
  type        = string
  default     = "ngc_azure_17_11"
}

variable "image_sku" {
  description = "Marketplace image SKU."
  type        = string
  default     = "ngc-base-version-25_9_1_gen2"
}

variable "image_version" {
  description = "Marketplace image version."
  type        = string
  default     = "latest"
}

###############################################################################
# Tagging
###############################################################################

variable "tags" {
  description = "Tags applied to all resources."
  type        = map(string)
  default = {
    project      = "ai-a100-devel"
    environment  = "dev"
    "managed-by" = "terraform"
  }
}
