###############################################################################
# Locals
###############################################################################

locals {
  # Prefer inline key content if provided, otherwise read the public key file.
  ssh_public_key = var.ssh_public_key != "" ? var.ssh_public_key : file(pathexpand(var.ssh_public_key_path))

  # -------------------------------------------------------------------------
  # Resource names, all derived from var.instance.
  #
  # With instance = "devel" these reproduce the original fixed names exactly,
  # EXCEPT the NIC, which is standardized to "...-nic" (it was an arbitrary
  # "vm-ai-a100-devel678" before; the state is fresh, so this is a deliberate,
  # one-time rename rather than a destructive change to a live resource).
  # -------------------------------------------------------------------------
  rg_name        = "ai-${var.instance}-a100-rg"      # devel -> ai-devel-a100-rg
  vm_name        = "vm-ai-a100-${var.instance}"      # devel -> vm-ai-a100-devel
  vnet_name      = "vm-ai-a100-${var.instance}-vnet" # devel -> vm-ai-a100-devel-vnet
  subnet_name    = "default"                         # unchanged
  public_ip_name = "vm-ai-a100-${var.instance}-ip"   # devel -> vm-ai-a100-devel-ip
  nsg_name       = "vm-ai-a100-${var.instance}-nsg"  # devel -> vm-ai-a100-devel-nsg
  nic_name       = "vm-ai-a100-${var.instance}-nic"  # devel -> vm-ai-a100-devel-nic (standardized)

  # Tag every resource with its instance name so resources are attributable
  # back to a specific instance in the portal / cost views.
  tags = merge(var.tags, { instance = var.instance })
}

###############################################################################
# Resource group
#
# The source ARM template assumed the resource group already existed. In
# Terraform we own its full lifecycle and create it here.
###############################################################################

resource "azurerm_resource_group" "this" {
  name     = local.rg_name
  location = var.location
  tags     = local.tags
}

###############################################################################
# Networking
###############################################################################

resource "azurerm_virtual_network" "this" {
  name                = local.vnet_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  address_space       = var.vnet_address_space
  tags                = local.tags
}

resource "azurerm_subnet" "default" {
  name                 = local.subnet_name
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = var.subnet_address_prefixes

  # The subnet references the vnet by NAME, so a region change (which force-
  # replaces the vnet) would otherwise leave the subnet untouched in the plan -
  # but replacing the vnet physically destroys the subnet, so the NIC then fails
  # with "subnet not found". Tie the subnet's lifecycle to the vnet: whenever the
  # vnet is replaced, recreate the subnet too (after the new vnet exists).
  lifecycle {
    replace_triggered_by = [azurerm_virtual_network.this.id]
  }
}

resource "azurerm_public_ip" "this" {
  name                = local.public_ip_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
}

resource "azurerm_network_security_group" "this" {
  name                = local.nsg_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.tags

  # SSH inbound. Source is restricted to var.ssh_source_address_prefix.
  # The ARM template used "*"; we deliberately do not.
  security_rule {
    name                       = "SSH"
    priority                   = 300
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.ssh_source_address_prefix
    destination_address_prefix = "*"
  }
}

resource "azurerm_network_interface" "this" {
  name                           = local.nic_name
  location                       = azurerm_resource_group.this.location
  resource_group_name            = azurerm_resource_group.this.name
  accelerated_networking_enabled = true
  tags                           = local.tags

  ip_configuration {
    name                          = "ipconfig1"
    subnet_id                     = azurerm_subnet.default.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.this.id
  }
}

resource "azurerm_network_interface_security_group_association" "this" {
  network_interface_id      = azurerm_network_interface.this.id
  network_security_group_id = azurerm_network_security_group.this.id
}

###############################################################################
# GPU virtual machine (Spot)
###############################################################################

resource "azurerm_linux_virtual_machine" "this" {
  name                = local.vm_name
  computer_name       = local.vm_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  size                = var.vm_size
  admin_username      = var.admin_username
  tags                = local.tags

  network_interface_ids = [
    azurerm_network_interface.this.id,
  ]

  # First-boot developer toolchain install via cloud-init (tools only; does not
  # clone repos). Disabled by setting enable_devtools = false.
  custom_data = var.enable_devtools ? base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
    setup_script_b64 = base64encode(file("${path.module}/../scripts/setup-devtools.sh"))
    admin_username   = var.admin_username
    prepull_models   = var.prepull_models ? "true" : "false"
  })) : null

  # SSH key auth only; no password login.
  disable_password_authentication = true

  admin_ssh_key {
    username   = var.admin_username
    public_key = local.ssh_public_key
  }

  # Purchasing model. For Regular (on-demand) VMs, eviction_policy and
  # max_bid_price must be unset; they only apply to Spot.
  priority        = var.vm_priority
  eviction_policy = var.vm_priority == "Spot" ? var.spot_eviction_policy : null
  max_bid_price   = var.vm_priority == "Spot" ? var.spot_max_bid_price : null

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = var.os_disk_storage_account_type
    # OS disk deletion on VM delete is enforced via the provider features block
    # in versions.tf (delete_os_disk_on_deletion = true).
  }

  # Marketplace image requires a matching plan block.
  source_image_reference {
    publisher = var.image_publisher
    offer     = var.image_offer
    sku       = var.image_sku
    version   = var.image_version
  }

  plan {
    name      = var.image_sku
    publisher = var.image_publisher
    product   = var.image_offer
  }

  # Boot diagnostics with a platform-managed storage account.
  boot_diagnostics {
    storage_account_uri = null
  }
}
