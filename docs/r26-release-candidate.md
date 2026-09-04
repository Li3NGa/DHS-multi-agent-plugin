# R26 — Native Release Candidate

R26 is the final repository-side release candidate gate for `dhs-multi-agent`.
It does not publish the package by itself.

## Candidate

- package: `dhs-multi-agent`
- candidate version: `0.2.0`
- Node baseline: `>=22.14.0`
- release tag convention: `npm-vX.Y.Z`

## Gate

`pnpm release:rc` runs the repository-side release invariants in one command:

1. GitHub Actions immutable supply-chain policy
2. Native source-of-truth policy
3. npm release contract
4. built public API contract
5. Native-first product surface contract
6. `npm pack --dry-run --json` tarball inspection

The candidate is considered repository-ready only when this command passes and
both the Native Runtime CI and Python compatibility matrix are green.

## Publish boundary

Actual publication remains an explicit release action. The npm workflow requires
GitHub OIDC Trusted Publishing for this exact repository/workflow and a deliberate
`npm-vX.Y.Z` tag. A passing `main` build is not itself a publication event.
