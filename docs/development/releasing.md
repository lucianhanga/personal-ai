# Releasing & Signing

PersonalAI releases are **signed with Sigstore/cosign** and ship a **CycloneDX SBOM**
(DEPENDENCY-POLICY). M0-9 provides the signing skeleton.

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
