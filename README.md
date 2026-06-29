# Azure A100 GPU Development Environment

Terraform plus helper scripts to provision, connect to, monitor, stop/start, and
tear down a single NVIDIA A100 GPU virtual machine on Azure for AI development.
The VM runs as a Spot instance to keep costs low, and uses the NVIDIA NGC
marketplace image so GPU drivers and the container toolkit are preinstalled.

## Scripts at a glance

| Script              | Purpose                                                              |
| ------------------- | ------------------------------------------------------------------- |
| `provision.sh`      | Accept marketplace terms, restrict SSH to your IP, init/plan/apply.  |
| `connect.sh`        | SSH into the VM (interactive shell, one-off command, or port-forward). |
| `monitor.sh`        | Read-only status dashboard (power state, SSH reachability, GPU).     |
| `stop.sh`           | Stop the VM (deallocate) to halt GPU billing. Keeps disk, IP, data.  |
| `start.sh`          | Resume a stopped (deallocated) VM.                                   |
| `deprovision.sh`    | Lifecycle: `--deallocate` / `--start` / `--destroy` (full teardown). |

`stop.sh` and `start.sh` are convenience wrappers over
`deprovision.sh --deallocate` and `deprovision.sh --start`.

## What gets created

All resources live in resource group `ai-devel-a100-rg` in `westeurope`:

- Resource group `ai-devel-a100-rg`
- Virtual network `vm-ai-a100-devel-vnet` (`10.0.0.0/16`)
- Subnet `default` (`10.0.0.0/24`)
- Public IP `vm-ai-a100-devel-ip` (Static, Standard SKU)
- Network security group `vm-ai-a100-devel-nsg` (one inbound SSH rule)
- Network interface `vm-ai-a100-devel678` (accelerated networking enabled)
- Linux VM `vm-ai-a100-devel`
  - Size `Standard_NC24ads_A100_v4` (single NVIDIA A100)
  - Spot priority, eviction policy `Deallocate`, max price `-1` (pay up to on-demand)
  - SSH key auth only (password auth disabled)
  - Premium_LRS OS disk, deleted when the VM is deleted
  - NVIDIA NGC marketplace image (`nvidia:ngc_azure_17_11:ngc-base-version-25_9_1_gen2`)
  - Boot diagnostics enabled (platform-managed storage)

All resources are tagged `project=ai-a100-devel`, `environment=dev`,
`managed-by=terraform`.

## Architecture

```
            Internet
               |
   SSH (22) restricted to your public IP
               |
        [ Public IP : Standard ]
               |
        [ NIC : accelerated networking ]
          |                 |
   [ NSG : SSH allow ]   [ Subnet default 10.0.0.0/24 ]
                              |
                     [ VNet 10.0.0.0/16 ]
               |
        [ VM vm-ai-a100-devel ]
          Spot, A100, NGC image, Premium OS disk
```

## Prerequisites

- An Azure subscription with quota for the `NC A100 v4` family (Spot) in
  `westeurope`. New subscriptions often have 0 GPU quota; request an increase
  if `terraform apply` fails with a quota error.
- Azure CLI (`az`) installed and logged in: `az login`
- Terraform `>= 1.6.0`
- An SSH key pair. Default public key path is `~/.ssh/id_rsa.pub`. Create one
  with `ssh-keygen -t ed25519` if needed (update `ssh_public_key_path` if you
  use a non-default path).
- `curl` (provision script uses it to detect your public IP), and `nc` or bash
  `/dev/tcp` for the SSH reachability check in the monitor script.

## Quickstart

From the repository root:

```bash
# 1. Provision (accepts marketplace terms, restricts SSH to your IP, applies)
./scripts/provision.sh

# 2. Connect to the VM
./scripts/connect.sh                # interactive SSH shell

# 3. Check status any time (read-only)
./scripts/monitor.sh
./scripts/monitor.sh --gpu          # also runs nvidia-smi over SSH
./scripts/monitor.sh --watch 15     # refresh every 15 seconds

# 4a. Stop GPU billing when idle (keeps disk and IP, resume quickly)
./scripts/stop.sh
./scripts/start.sh                  # resume later

# 4b. Tear everything down (DELETES the disk and all data)
./scripts/deprovision.sh --destroy
```

## Connecting to the VM

`connect.sh` reads the public IP and admin user from the Terraform outputs,
verifies the VM is running, and opens an SSH session. It accepts a flag, but no
arguments are required:

```bash
./scripts/connect.sh                          # interactive shell
./scripts/connect.sh nvidia-smi               # run one command and exit
./scripts/connect.sh -i ~/.ssh/mykey          # use a specific private key
./scripts/connect.sh -- -L 8888:localhost:8888  # forward a port (e.g. Jupyter)
```

If the VM is stopped/deallocated, `connect.sh` tells you to run `./scripts/start.sh`
first. You can also connect manually with the command printed by `provision.sh`
or shown by `terraform -chdir=terraform output ssh_connection_string`.

## Spot VM caveat (read this)

This is a **Spot** VM. Azure can **evict** it at any time when it needs the
capacity back. With eviction policy `Deallocate`, eviction stops the VM but
keeps the OS disk, so your data survives and you can start it again later
(subject to spot capacity being available). Treat the VM as ephemeral compute:
keep important work in source control or on durable storage, not only on the
local disk.

## Cost-saving guidance: deallocate vs destroy

| Action                  | GPU/compute charge | OS disk charge | Public IP charge | Data kept | Resume |
| ----------------------- | ------------------ | -------------- | ---------------- | --------- | ------ |
| `--deallocate` (default)| stopped            | still billed   | still billed     | yes       | fast   |
| `--destroy`             | stopped            | removed        | removed          | no        | full reprovision |

- Use `stop.sh` (deallocate) between work sessions: you stop paying for the
  expensive A100 compute but keep a small bill for the Premium OS disk and the
  Standard static public IP, and you can resume in minutes with `start.sh`.
- Use `deprovision.sh --destroy` when you are done with the environment entirely:
  it removes all resources and all charges, but the disk and its data are gone.
- A `stopped` (but still allocated) VM can still incur compute charges. Always
  prefer `deallocated`, which is exactly what `stop.sh` does. The monitor script
  flags the difference.

> Note: `stop.sh`/`start.sh` and `deprovision.sh --deallocate`/`--start` are the
> same operation. Use whichever name you find clearer.

## SSH source-IP security note

The original ARM template allowed SSH from `*` (the entire internet). This
project does **not**. The NSG SSH rule source is the Terraform variable
`ssh_source_address_prefix`:

- `provision.sh` auto-detects your current public IP and restricts SSH to that
  single address (`<ip>/32`). Override with `--ssh-cidr <CIDR>`.
- The variable has a validation rule that **rejects `*`**.
- If your public IP changes (home ISP, VPN, travel), re-run `provision.sh` (or
  `terraform apply` with a new `ssh_source_address_prefix`) to update the rule.

For a corporate range, pass a wider CIDR, for example
`--ssh-cidr 198.51.100.0/24`.

## Running Terraform directly (optional)

The scripts are the recommended path, but you can drive Terraform yourself:

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # edit ssh_source_address_prefix
terraform init
terraform plan
terraform apply
```

Remember to accept the marketplace terms first if you skip `provision.sh`:

```bash
az vm image terms accept \
  --publisher nvidia --offer ngc_azure_17_11 --plan ngc-base-version-25_9_1_gen2
```

## Configuration reference (Terraform variables)

All defaults mirror the source ARM template. Override via `terraform.tfvars`,
`-var` flags, or `TF_VAR_*` environment variables. Most-used variables:

| Variable                       | Default                      | Description                                                  |
| ------------------------------ | ---------------------------- | ------------------------------------------------------------ |
| `location`                     | `westeurope`                 | Azure region for all resources.                              |
| `resource_group_name`          | `ai-devel-a100-rg`           | Resource group that holds the environment.                   |
| `vm_name`                      | `vm-ai-a100-devel`           | VM name (and computer name).                                 |
| `vm_size`                      | `Standard_NC24ads_A100_v4`   | VM size (single NVIDIA A100, NC A100 v4 family).             |
| `admin_username`               | `azureuser`                  | SSH login user.                                              |
| `ssh_public_key_path`          | `~/.ssh/id_rsa.pub`          | Public key file used for VM auth (when `ssh_public_key` empty). |
| `ssh_public_key`               | `""`                         | Inline public key; takes precedence over the path.          |
| `ssh_source_address_prefix`    | `127.0.0.1/32`               | Source CIDR allowed on port 22. `provision.sh` sets this to your IP. `*` is rejected. |
| `os_disk_storage_account_type` | `Premium_LRS`                | OS disk type.                                                |
| `spot_max_bid_price`           | `-1`                         | Max USD/hour for Spot; `-1` = pay up to on-demand (no price eviction). |
| `spot_eviction_policy`         | `Deallocate`                 | `Deallocate` keeps the disk on eviction; `Delete` removes it. |
| `vnet_address_space`           | `["10.0.0.0/16"]`            | VNet address space.                                          |
| `subnet_address_prefixes`      | `["10.0.0.0/24"]`            | Default subnet prefixes.                                     |
| `image_publisher` / `image_offer` / `image_sku` / `image_version` | NVIDIA NGC values | Marketplace image coordinates (and the required `plan`). |
| `tags`                         | project/environment/managed-by | Tags applied to all resources.                            |

Naming variables (`vnet_name`, `subnet_name`, `public_ip_name`, `nic_name`,
`nsg_name`) also exist and default to the ARM template names. See
`terraform/variables.tf` for the complete list and inline validation rules.

## Remote state (team use)

Default state is local (`terraform/terraform.tfstate`, gitignored). For shared
use, enable the commented `azurerm` backend block in `terraform/versions.tf`
and run `terraform init -migrate-state`.

## Repository layout

```
.
├── README.md
├── .gitignore
├── scripts/
│   ├── provision.sh      # accept terms, restrict SSH, init/plan/apply
│   ├── connect.sh        # SSH into the VM (shell, command, or port-forward)
│   ├── stop.sh           # deallocate the VM (halt GPU billing, keep data)
│   ├── start.sh          # resume a deallocated VM
│   ├── deprovision.sh    # deallocate | start | destroy
│   └── monitor.sh        # read-only status dashboard
└── terraform/
    ├── versions.tf       # provider/version pins, backend guidance
    ├── variables.tf      # all inputs with template-matching defaults
    ├── main.tf           # RG, network, NSG, NIC, VM
    ├── outputs.tf        # IP, SSH string, names
    └── terraform.tfvars.example
```

## Notes and deviations from the source ARM template

- The resource group is **created** by Terraform (the ARM template assumed it
  already existed).
- SSH source is **restricted** to your IP instead of `*` (security hardening).
- Everything else mirrors the template: names, sizes, image, plan, Spot policy,
  Premium OS disk, accelerated networking, and the SSH-only login model.
