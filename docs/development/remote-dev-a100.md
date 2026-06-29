# Remote A100 dev VM

Provision an Azure **A100 80GB** Spot VM (NVIDIA NGC image, GPU drivers
preinstalled) for development, sync your local DB/Claude config onto it, and tear
it down when done. The Terraform and all lifecycle/ops scripts live in
[`infra/`](../../infra/) (see [`infra/README.md`](../../infra/README.md) for the
full reference). All commands below are run from the repo root.

Default region is `germanywestcentral`; default instance name is `devel`. Add
`-n <instance>` to any command to target another machine (each name gets its own
resource group, network, VM, and Terraform state, so you can run several at once).

## First-time setup

```bash
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars  # edit if needed
az login                                                                       # Azure CLI auth
infra/scripts/check-quota.sh                                                   # confirm A100 quota/capacity
```

The dedicated SSH key `~/.ssh/ai-a100-devel` is created automatically by
`provision.sh` on first run; `connect.sh` / `tunnel.sh` / the sync scripts reuse it.

## Lifecycle cheatsheet

### 1. provision — create the VM

```bash
infra/scripts/provision.sh -r germanywestcentral -y
```

Accepts the marketplace terms, restricts SSH to your current public IP (`/32`),
init/plan/applies the Terraform, and installs the dev toolchain on first boot
(uv/Python 3.12, Node 22/pnpm, Docker, Ollama + pre-pulled models, gh).
Prereqs: `az login`, A100 quota. Spot by default; add `--on-demand` for a
non-evictable (pricier) VM, `--skip-models` to skip the ~21 GB Ollama pull.

### 2. start — resume a stopped VM

```bash
infra/scripts/start.sh -y
```

Starts a previously stopped (deallocated) instance. As a Spot VM, start can fail
if there is no spot capacity right now.

Connect / forward ports once it is running:

```bash
infra/scripts/connect.sh                 # interactive SSH shell
infra/scripts/connect.sh nvidia-smi      # run one command and exit
infra/scripts/tunnel.sh --dev            # forward UI 5173 + backend 8765 to localhost
infra/scripts/tunnel.sh --api            # forward just the backend (8765)
```

On the VM, run the app with `make db` then `make run-backend` (port 8765) and
`make run-ui` (port 5173); reach them locally through the tunnel.

### 3. sync — push your data and config to the VM

```bash
infra/scripts/sync-data.sh   -n devel            # push Postgres (replaces remote DB)
infra/scripts/sync-data.sh   -n devel --no-docs  # everything EXCEPT document corpus + KAG
infra/scripts/sync-data.sh   -n devel --pull     # bring remote DB back to local
infra/scripts/sync-claude.sh -n devel            # push Claude settings/commands/MCP config
```

`sync-data.sh` does a Postgres dump/restore over SSH; the project's `make db`
Postgres container must be running on both ends. `--push` is the default and
replaces the destination DB.

### 4. stop — pause billing, keep data

```bash
infra/scripts/stop.sh -y
```

Deallocates the VM: GPU/compute billing stops, but the disk, public IP, network,
and data are kept. Resume in minutes with `start.sh`.

### 5. destroy — delete everything

```bash
infra/scripts/destroy.sh -y
```

`terraform destroy` of the instance: VM, OS disk, network, public IP, resource
group. ALL DATA IS LOST. Irreversible.

### Monitor cost / status any time

```bash
infra/scripts/monitor.sh            # all instances + standing IP/disk monthly cost (read-only)
infra/scripts/monitor.sh --list     # compact inventory table
```

## Gotchas

- **stop != destroy.** `stop.sh` still bills the Premium OS disk and the Standard
  static public IP 24/7; only `destroy.sh` removes all charges (and all data).
- **`--no-docs` means re-ingest.** Syncing with `--no-docs` excludes the document
  corpus and knowledge graph (KAG); re-ingest the documents on the destination.
- **`.env` and `mcp.json` are not in the DB.** `sync-data.sh` moves only Postgres.
  `sync-claude.sh` syncs Claude config (incl. MCP); the app's `.env` is copied by
  hand or via `sync-claude.sh --project`.
- **Spot VMs get evicted.** Eviction deallocates (keeps the disk), so treat the VM
  as ephemeral compute — keep important work in git or durable storage.
- **IP changed?** If your public IP changes (VPN/travel/ISP), re-run
  `provision.sh` to update the NSG SSH rule.
