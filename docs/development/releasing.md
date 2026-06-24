# Releasing & Signing

PersonalAI releases are **signed with Sigstore/cosign** and ship a **CycloneDX SBOM**
(DEPENDENCY-POLICY). M0-9 provides the signing skeleton.

## Versioning

PersonalAI uses **one product version**, kept as a single source of truth.

- **Canonical source:** the root [`VERSION`](../../VERSION) file holds the product version
  (currently `0.8.3`). This is the value to read when you need "the product version."
- **Runtime mirror:** `apps/backend/src/personalai_backend/__init__.py` `__version__` must be kept
  **in sync** with `VERSION`. It is the value the running app actually reports — `app.py` feeds it
  into the OpenAPI document's `info.version` and the unversioned `GET /version` endpoint (nothing
  reads the `VERSION` file at runtime, so this string is what ships).
- **Packaged product manifests** carry the same product version: `apps/backend/pyproject.toml`,
  `tools/mcp/pyproject.toml`, and `apps/ui/package.json`.
- **Internal-only libraries stay at `0.0.0`** on purpose: `contracts`, `core`, `providers/*`,
  `storage/*`, `modalities/*`, and `benchmarks`. They are never published independently — they are
  consumed only as `uv`-workspace path/source dependencies of the backend app, so a real version
  number would be noise. The single shared `uv.lock` at the repo root pins everything; member
  versions don't gate resolution. Leaving them at `0.0.0` keeps the product version unambiguous.

**Policy (pre-1.0)** — same as the [CHANGELOG](../../CHANGELOG.md) header: `MAJOR` stays `0` until
the first stable release; `MINOR` bumps as each milestone (M1, M2, …) lands; `PATCH` bumps for
fixes/UX tweaks between milestones. The shipped state is **M8.3**, so the version is **0.8.3**. The
HTTP API is versioned independently in the URL path (`/api/v1`).

**To bump the product version**, update all five product files together — `VERSION`, the backend
`__init__.py` `__version__`, `apps/backend/pyproject.toml`, `tools/mcp/pyproject.toml`, and
`apps/ui/package.json` — then cut the CHANGELOG release (move `[Unreleased]` into a dated
`[x.y.z]` section and update the compare-link footers). Tagging is `vX.Y.Z`.

> Status: the pipeline and a CI signing smoke test exist (M0-9). Distribution channels and a
> reproducible-build guarantee are refined in M11.

## What gets signed

On a published GitHub release (`.github/workflows/release.yml`):

1. Python distributions are built (`uv build --all-packages` -> `dist/`).
2. A CycloneDX SBOM is generated (`scripts/generate_sbom.sh`).
3. Each artifact **and** the SBOM are signed **keyless** with cosign, using the workflow's GitHub
   OIDC identity (no long-lived keys). This produces a `.sig` (signature) and `.crt` (certificate)
   per file, recorded in the public Sigstore transparency log.
4. Each is verified in-workflow, then attached to the release.

The workflow can be run as a dry run via **workflow_dispatch** (artifacts are uploaded as a CI
artifact instead of to a release).

## Verifying a release artifact

```bash
cosign verify-blob <artifact> \
  --signature <artifact>.sig \
  --certificate <artifact>.crt \
  --certificate-identity-regexp "https://github.com/lucianhanga/personal-ai/.*" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com"
```

A successful verification proves the artifact was produced by this repo's release workflow and has
not been tampered with.

## CI signing smoke test

Every PR/push runs a **`Signing smoke (cosign)`** job that signs and verifies a throwaway artifact
with an **ephemeral key, fully offline** (`--tlog-upload=false`, `--insecure-ignore-tlog=true`).
This proves the signing toolchain works without polluting the public transparency log. Locally:

```bash
# requires cosign on PATH
make signing-smoke
```

## Reproducible builds (investigation note)

Goal: identical inputs produce byte-identical artifacts so signatures are independently
reproducible. Current status and next steps:

- The SBOM generator already uses `--output-reproducible` for stable output.
- Python wheels via `uv build` are largely deterministic but embed timestamps; pinning
  `SOURCE_DATE_EPOCH` and auditing the build for nondeterminism is a follow-up (tracked for M11).
- No reproducible-build guarantee is claimed yet.
