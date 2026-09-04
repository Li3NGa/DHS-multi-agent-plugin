# R18 GitHub Actions Supply-Chain Pinning

## Objective

Make CI execution reproducible against immutable Git commits instead of mutable action tags or branches.

## Immutable action baseline

| Action | Version | Commit |
| --- | --- | --- |
| `actions/checkout` | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `actions/setup-node` | v7.0.0 | `820762786026740c76f36085b0efc47a31fe5020` |
| `actions/setup-python` | v7.0.0 | `5fda3b95a4ea91299a34e894583c3862153e4b97` |
| `actions/upload-artifact` | v7.0.1 | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` |
| `actions/download-artifact` | v8.0.1 | `3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c` |
| `pypa/gh-action-pypi-publish` | v1.14.2 | `dc37677b2e1c63e2034f94d8a5b11f265b73ba33` |
| `softprops/action-gh-release` | v3.0.2 | `3d0d9888cb7fd7b750713d6e236d1fcb99157228` |

Version comments remain next to each pinned reference so reviewers can map the immutable commit to the intended release.

## Automated enforcement

`scripts/check-actions-runtime.mjs` now performs a supply-chain check instead of only checking for deprecated Node runtimes. It scans every workflow under `.github/workflows/` and requires:

- every external Action to use a 40-character commit SHA;
- every known Action to match the expected audited commit;
- every known Action to retain the expected version comment;
- every required external Action to appear in the workflow set.

Local command:

```bash
pnpm actions:check
```

The guard runs in the normal CI, Native Runtime CI, Security Audit, Python publishing workflow, and Native npm publishing workflow.

## Provenance notes

The R18 baseline was resolved from the upstream release tags. The `pypa/gh-action-pypi-publish` v1.14.2 tag points to commit `dc37677b...` and its release tag is cryptographically verified by GitHub. The other pinned references were resolved from their corresponding upstream version tags.

## Scope

R18 is CI/release infrastructure only. It does not alter Native runtime execution, Python runtime execution, the public API, or package behavior.
