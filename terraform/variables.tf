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
# Instance identity
#
# A single string that names this VM instance. ALL resource names are derived
# from it in main.tf (see the locals block), so two different instance names
# produce two fully independent stacks (resource group, network, VM) that can
# coexist - even in the same region. Each instance also gets its own Terraform
# state via a workspace named after it (the helper scripts manage this).
#
# The default "devel" reproduces the original fixed resource names exactly, so
# existing behavior is unchanged when no name is given.
###############################################################################

variable "instance" {
  description = "Instance name. All resource names derive from this (see locals in main.tf). Default 'devel' reproduces the original names. Each instance has its own resource group, network, VM, and Terraform workspace/state."
  type        = string
  default     = "devel"

  validation {
    # Lowercase letters, digits and hyphens; must start with a letter and end
    # with a letter or digit; total length 2-24. This keeps every derived Azure
    # resource name (and the Linux computer name) valid.
    condition     = can(regex("^[a-z][a-z0-9-]{0,22}[a-z0-9]$", var.instance))
    error_message = "instance must be 2-24 chars of lowercase letters, digits and hyphens, start with a letter, and not end with a hyphen."
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
# Developer toolchain (cloud-init)
###############################################################################

variable "enable_devtools" {
  description = "Install the developer toolchain (uv/Python 3.12, Node 22/pnpm, Docker, Ollama, gh, build libs) on first boot via cloud-init. Tools only; does not clone the project repos."
  type        = bool
  default     = true
}

variable "prepull_models" {
  description = "Pre-pull the shared Ollama models (qwen3-embedding:0.6b + qwen3.6:35b-a3b, ~21 GB) during first-boot setup. Only applies when enable_devtools is true."
  type        = bool
  default     = true
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
