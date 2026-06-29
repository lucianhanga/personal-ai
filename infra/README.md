# Azure A100 GPU Development Environment

Terraform plus helper scripts to provision, connect to, monitor, stop/start, and
tear down NVIDIA A100 GPU virtual machines on Azure for AI development. Each VM
runs as a Spot instance to keep costs low, and uses the NVIDIA NGC marketplace
image so GPU drivers and the container toolkit are preinstalled.

## Named instances (run several at once)

You can run multiple independent machines at the same time - including several in
the **same region** - each identified by a `--name`. Every name gets its own
resource group, network, VM, and its own Terraform state (a Terraform workspace
named after the instance), so instances never collide:

```bash
./scripts/provision.sh --name train -r eastus
./scripts/provision.sh --name web   -r eastus       # second VM, same region
./scripts/provision.sh --name eu    -r westeurope
./scripts/monitor.sh --all                          # all instances + total cost
./scripts/connect.sh --name train
./scripts/stop.sh    --name web                     # halt billing on one
./scripts/destroy.sh --name eu                      # delete one entirely
```

Key points:

- The default name is **`devel`** (`--name` omitted), which reproduces the
  original resource names exactly, so existing usage is unchanged.
- For an instance named `<name>`, all resources derive from it:
  `ai-<name>-a100-rg` (resource group), `vm-ai-a100-<name>` (VM),
  `vm-ai-a100-<name>-vnet`, `vm-ai-a100-<name>-ip`, `vm-ai-a100-<name>-nsg`,
  `vm-ai-a100-<name>-nic`; the subnet stays `default`. Each is tagged
  `instance=<name>`.
- Each name is a separate Terraform workspace (separate state). The scripts
  select or create the right workspace for you; you never manage workspaces by
  hand.
- The **SSH key is shared** across all instances (one dedicated key, created
  once - see Prerequisites).
- Running several **regions** in parallel also helps with the A100 Spot capacity
  problem: if one region cannot place a Spot VM, another often can.

The instance name must be 2-24 characters: lowercase letters, digits and
hyphens, starting with a letter (validated by Terraform).

## Scripts at a glance

The five core lifecycle verbs:

| Verb (script)   | Purpose                                                                  |
| --------------- | ------------------------------------------------------------------------ |
| `provision.sh`  | **Create** the machine (terms, restrict SSH to your IP, init/plan/apply). |
| `start.sh`      | **Start** a stopped (deallocated) machine.                               |
| `stop.sh`       | **Stop** the machine: deallocate it - halts GPU billing, keeps disk + data. |
| `destroy.sh`    | **Destroy** the machine and ALL its resources (irreversible).            |
| `monitor.sh`    | **Monitor**: status + live cost. Discovers instances from Azure; bare run shows ALL of them, plus standing IP + disk monthly cost. |

Access / support scripts:

| Script              | Purpose                                                              |
| ------------------- | ------------------------------------------------------------------- |
| `connect.sh`        | SSH into the machine (shell, one-off command, or port-forward).     |
| `tunnel.sh`         | SSH local port-forwarding (Jupyter / TensorBoard / Ollama presets). |
| `check-quota.sh`    | Survey A100 quota + SKU availability across regions.                |
| `setup-devtools.sh` | Idempotent toolchain installer run on the VM (via cloud-init).      |

All instance-aware scripts accept `-n, --name <name>` (alias `--instance`,
default `devel`) to target a specific machine.

`monitor.sh` is the exception and is a pure read-only **Azure** tool: it
discovers instances directly from Azure resource groups (those named
`ai-<name>-a100-rg`), independent of local Terraform state or workspaces. A bare
`monitor.sh` therefore inspects **every** instance that exists in the
subscription (equivalent to `--all`); `monitor.sh --name <name>` narrows to one.
For each instance it also lists the **standing resources** (public IPs and
managed disks) with their estimated **monthly** cost - the charges that accrue
24/7 even when the VM is stopped, failed, or never created.

Two extra views help at a glance:

- `monitor.sh --list` (alias `-l`) prints a compact **inventory table**, one row
  per instance: `INSTANCE | REGION | STATUS | RESOURCES | STANDING $/mo`, plus a
  combined standing total. `STATUS` is `running`, `stopped`, `partial`
  (resources exist but no VM - an incomplete or failed provision that is still
  billing), or `empty`.
- `monitor.sh --top` (alias `--live`) is a full-screen **live dashboard**: it
  takes over the terminal (alternate screen buffer), redraws in place every few
  seconds (default 5s, or set `--watch <secs>`), and restores the terminal
  cleanly on exit or Ctrl-C (press `q` to quit). It also works with `--list`
  (live inventory). When stdout is not a TTY it falls back to a single render, so
  piping and redirection still work.

`start.sh` / `stop.sh` / `destroy.sh` are thin verbs over a shared internal
engine (`deprovision.sh`); call the verbs, not the engine. Note "stop" always
**deallocates** (releases the GPU so compute billing stops) - there is
deliberately no plain stop that keeps the VM allocated and still billing.

## What gets created

For the default instance `devel`, all resources live in resource group
`ai-devel-a100-rg` (for any other `--name`, substitute the name below):

- Resource group `ai-devel-a100-rg`
- Virtual network `vm-ai-a100-devel-vnet` (`10.0.0.0/16`)
- Subnet `default` (`10.0.0.0/24`)
- Public IP `vm-ai-a100-devel-ip` (Static, Standard SKU)
- Network security group `vm-ai-a100-devel-nsg` (one inbound SSH rule)
- Network interface `vm-ai-a100-devel-nic` (accelerated networking enabled)
- Linux VM `vm-ai-a100-devel`
  - Size `Standard_NC24ads_A100_v4` (single NVIDIA A100)
  - Spot priority, eviction policy `Deallocate`, max price `-1` (pay up to on-demand)
  - SSH key auth only (password auth disabled)
  - Premium_LRS OS disk, deleted when the VM is deleted
  - NVIDIA NGC marketplace image (`nvidia:ngc_azure_17_11:ngc-base-version-25_9_1_gen2`)
  - Boot diagnostics enabled (platform-managed storage)

All resources are tagged `project=ai-a100-devel`, `environment=dev`,
`managed-by=terraform`, and `instance=<name>`.

> Note: the NIC is named `vm-ai-a100-<name>-nic`. The original template used an
> arbitrary suffix (`vm-ai-a100-devel678`); it has been standardized to `-nic`
> for consistency across instances.

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
- An SSH key pair. This project uses a **dedicated key created once** at
  `~/.ssh/ai-a100-devel` and reused for every VM it provisions. `provision.sh`
  generates it automatically on first run if it does not exist, and `connect.sh`
  / `tunnel.sh` default to it (override with `-i <path>`). To use your own key
  instead, set `ssh_public_key_path` (or `ssh_public_key`).
- `curl` (provision script uses it to detect your public IP), and `nc` or bash
  `/dev/tcp` for the SSH reachability check in the monitor script.

## Quickstart

From the repository root:

```bash
# 1. Provision (accepts marketplace terms, restricts SSH to your IP, applies)
./scripts/provision.sh

# 2. Connect to the VM
./scripts/connect.sh                # interactive SSH shell

# 3. Check status any time (read-only; discovers all instances from Azure)
./scripts/monitor.sh                # ALL instances + standing IP/disk monthly cost
./scripts/monitor.sh --name devel   # just one instance
./scripts/monitor.sh --gpu          # also runs nvidia-smi over SSH
./scripts/monitor.sh --watch 15     # refresh every 15 seconds

# 4a. Stop when idle (deallocate; halts GPU billing, keeps disk and data)
./scripts/stop.sh
./scripts/start.sh                  # resume later

# 4b. Destroy everything (DELETES the disk and all data)
./scripts/destroy.sh
```

The default machine is `devel`. Add `--name <name>` to any verb to target a
specific machine (e.g. `./scripts/stop.sh --name train`).

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

## Developer toolchain (auto-installed on first boot)

By default `provision.sh` installs a developer toolchain on the VM via cloud-init
(`terraform/cloud-init.yaml.tftpl` runs `scripts/setup-devtools.sh` on first
boot). It installs the tools needed by the `doktokNG` and `personalAI` projects
(tools only - it does not clone the repos):

- build libs + native deps (`libpq`, `libmagic`, `libGL`, `libgomp`, ...)
- `nvtop` (an interactive GPU "top" for live NVIDIA GPU/VRAM/process monitoring)
- git + GitHub CLI (`gh`)
- Docker + compose v2
- `uv` + Python 3.12
- Node.js 22 + `pnpm` 11.5.1
- Ollama (uses the A100 GPU automatically)
- pre-pulls the shared Ollama models `qwen3-embedding:0.6b` and
  `qwen3.6:35b-a3b` (~21 GB)

Flags:
- `provision.sh --no-devtools` - skip the toolchain entirely.
- `provision.sh --skip-models` - install tools but do not pre-pull the models.

On first run the installer also refreshes the OS packages (`apt-get update` and
`apt-get upgrade -y`) before installing the toolchain, so the base image starts
up to date.

Progress is logged on the VM at `/var/log/devtools-setup.log`; a summary marker
is written to `/var/lib/devtools-setup.done` when it finishes. The install is
idempotent and can be re-run: `sudo TARGET_USER=azureuser bash /opt/devtools/setup-devtools.sh`.

## Spot VM caveat (read this)

This is a **Spot** VM. Azure can **evict** it at any time when it needs the
capacity back. With eviction policy `Deallocate`, eviction stops the VM but
keeps the OS disk, so your data survives and you can start it again later
(subject to spot capacity being available). Treat the VM as ephemeral compute:
keep important work in source control or on durable storage, not only on the
local disk.

## Cost-saving guidance: stop vs destroy

| Action          | GPU/compute charge | OS disk charge | Public IP charge | Data kept | Resume |
| --------------- | ------------------ | -------------- | ---------------- | --------- | ------ |
| `stop.sh`       | stopped            | still billed   | still billed     | yes       | fast   |
| `destroy.sh`    | stopped            | removed        | removed          | no        | full reprovision |

- Use `stop.sh` between work sessions: you stop paying for the expensive A100
  compute but keep a small bill for the Premium OS disk and the Standard static
  public IP, and you can resume in minutes with `start.sh`.
- Use `destroy.sh` when you are done with the machine entirely: it removes all
  resources and all charges, but the disk and its data are gone.
- `stop.sh` always **deallocates** (the right, cheap "off"). A VM that is merely
  stopped-but-allocated still incurs compute charges - the scripts never do that.

To see exactly what is still costing money, run `monitor.sh`. Alongside the
compute figure it prints a **Standing resources** section for each instance -
every public IP and managed disk with an estimated **monthly** cost and a
per-instance subtotal, plus a combined standing total across all instances.
Because monitor discovers instances from Azure (not from local Terraform state),
this surfaces leftover billable resources even after a partial or failed
provision, or when a VM was destroyed but its public IP or disk was left behind.
The two figures are kept distinct on purpose: **compute** is an hourly accrual
that only runs while a VM is on; **standing** is a monthly estimate for the
IP + disk resources that bill 24/7 regardless of VM power state.

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
# Pick the instance's workspace (the scripts do this for you). For the default:
terraform workspace select devel || terraform workspace new devel
terraform plan  -var "instance=devel"
terraform apply -var "instance=devel"
```

Use a different `instance` value (and a matching workspace) for each additional
machine, e.g. `terraform workspace new train` and `-var "instance=train"`.

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
| `instance`                     | `devel`                      | Instance name. ALL resource names derive from it; also the Terraform workspace. |
| `location`                     | `westeurope`                 | Azure region for all resources.                              |
| `vm_size`                      | `Standard_NC24ads_A100_v4`   | VM size (single NVIDIA A100, NC A100 v4 family).             |
| `admin_username`               | `azureuser`                  | SSH login user.                                              |
| `ssh_public_key_path`          | `~/.ssh/ai-a100-devel.pub`   | Dedicated public key (created once by provision.sh) used for every VM, when `ssh_public_key` empty. |
| `ssh_public_key`               | `""`                         | Inline public key; takes precedence over the path.          |
| `ssh_source_address_prefix`    | `127.0.0.1/32`               | Source CIDR allowed on port 22. `provision.sh` sets this to your IP. `*` is rejected. |
| `os_disk_storage_account_type` | `Premium_LRS`                | OS disk type.                                                |
| `spot_max_bid_price`           | `-1`                         | Max USD/hour for Spot; `-1` = pay up to on-demand (no price eviction). |
| `spot_eviction_policy`         | `Deallocate`                 | `Deallocate` keeps the disk on eviction; `Delete` removes it. |
| `vnet_address_space`           | `["10.0.0.0/16"]`            | VNet address space.                                          |
| `subnet_address_prefixes`      | `["10.0.0.0/24"]`            | Default subnet prefixes.                                     |
| `image_publisher` / `image_offer` / `image_sku` / `image_version` | NVIDIA NGC values | Marketplace image coordinates (and the required `plan`). |
| `tags`                         | project/environment/managed-by | Tags applied to all resources.                            |

All resource names are **derived** from `instance` in a `locals` block in
`terraform/main.tf` (resource group, VM, VNet, public IP, NSG, NIC); the subnet
stays `default`. There are no longer per-name variables - set `instance` (or use
the scripts' `--name`) and every name follows. See `terraform/variables.tf` and
`terraform/main.tf` for the complete list and inline validation rules.

## Remote state (team use)

Default state is local and **per-workspace**: each instance keeps its state in
`terraform/terraform.tfstate.d/<name>/` (all gitignored). For shared use, enable
the commented `azurerm` backend block in `terraform/versions.tf` and run
`terraform init -migrate-state`; the azurerm backend keys workspace state by name
automatically, so multiple instances stay isolated there too.

## Repository layout

```
.
├── README.md
├── .gitignore
├── scripts/
│   ├── provision.sh      # CREATE the machine (terms, SSH, init/plan/apply; --name)
│   ├── start.sh          # START a stopped (deallocated) machine (--name)
│   ├── stop.sh           # STOP (deallocate): halt GPU billing, keep data (--name)
│   ├── destroy.sh        # DESTROY the machine and all resources (--name)
│   ├── monitor.sh        # MONITOR: status + compute/standing cost; discovers all instances from Azure (--name, --all)
│   ├── connect.sh        # SSH into the machine (shell, command, port-forward; --name)
│   ├── tunnel.sh         # SSH local port-forwarding presets (--name)
│   ├── deprovision.sh    # internal engine behind start/stop/destroy (--name)
│   ├── setup-devtools.sh # first-boot toolchain installer (runs on the VM)
│   └── check-quota.sh    # report A100 vCPU quota by region
└── terraform/
    ├── versions.tf          # provider/version pins, backend guidance
    ├── variables.tf         # all inputs (instance + the rest) with defaults
    ├── main.tf              # locals (names from instance), RG, network, NSG, NIC, VM, cloud-init
    ├── outputs.tf           # instance, IP, SSH string, names
    ├── cloud-init.yaml.tftpl # first-boot toolchain install template
    └── terraform.tfvars.example
```

## Notes and deviations from the source ARM template

- The resource group is **created** by Terraform (the ARM template assumed it
  already existed).
- SSH source is **restricted** to your IP instead of `*` (security hardening).
- Everything else mirrors the template: names, sizes, image, plan, Spot policy,
  Premium OS disk, accelerated networking, and the SSH-only login model.
