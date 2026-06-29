terraform {
  # Pinned to a recent stable Terraform release line.
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source = "hashicorp/azurerm"
      # azurerm 4.x is the current stable major line. Pinned to 4.x to get a
      # reproducible provider while still receiving patch/minor updates.
      version = "~> 4.20"
    }
  }

  # ---------------------------------------------------------------------------
  # Remote state (recommended for team use). Left commented on purpose so the
  # default experience uses simple local state (terraform.tfstate in this dir).
  #
  # To enable a shared azurerm backend:
  #   1. Create a storage account + container once (out of band), e.g.:
  #        az group create -n tfstate-rg -l westeurope
  #        az storage account create -n <uniquestorage> -g tfstate-rg \
  #            -l westeurope --sku Standard_LRS --min-tls-version TLS1_2
  #        az storage container create -n tfstate --account-name <uniquestorage>
  #   2. Uncomment and fill the block below, then run: terraform init -migrate-state
  #
  # backend "azurerm" {
  #   resource_group_name  = "tfstate-rg"
  #   storage_account_name = "<uniquestorage>"
  #   container_name       = "tfstate"
  #   key                  = "ai-a100-devel.tfstate"
  #   use_azuread_auth     = true
  # }
}

provider "azurerm" {
  # Pin the subscription explicitly. Without this the provider uses the az CLI
  # default subscription, which previously caused deployments to land in the
  # wrong (similarly-named) subscription in a different tenant.
  subscription_id = var.subscription_id

  features {
    virtual_machine {
      # Ensure dependent resources are cleaned up cleanly on destroy.
      delete_os_disk_on_deletion = true
    }
  }
}
