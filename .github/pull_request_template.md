<!-- PR title should follow Conventional Commits, e.g. feat(contracts): add ModelProvider port -->

## Summary

<!-- What does this change do and why? -->

Closes #

## Type of change

- [ ] feat
- [ ] fix
- [ ] docs
- [ ] refactor / chore / test / ci / build
- [ ] security

## Checklist

- [ ] Follows GitHub flow (branch off `main`, PR into `main`).
- [ ] Conventional Commit title.
- [ ] CI passes.
- [ ] No secrets committed.
- [ ] Tests added/updated where applicable.
- [ ] **If dependencies changed:** `docs/supply-chain/SUPPLY-CHAIN.md` + SBOM updated in this PR.
- [ ] **If a contract/schema changed:** version bumped; ADR added if a stable port/contract changed.
- [ ] Docs updated to match behavior.

## Modularity check

- [ ] Change is additive (new adapter behind an existing port + registry entry + schema) and
      does **not** modify the stable core unnecessarily. If the core changed, explain why:

<!-- explanation -->

## Security considerations

<!-- New trust boundaries, permissions, egress, or untrusted input handled? -->
