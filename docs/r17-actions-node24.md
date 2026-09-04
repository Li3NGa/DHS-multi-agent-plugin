# R17 GitHub Actions Node 24 Runtime

## Objective

Remove the repository's dependence on deprecated Node 20-based GitHub Actions runtimes and prevent future workflow regressions.

## Action baseline

The repository uses the Node 24-compatible major lines below:

| Action | Required major | Purpose |
| --- | --- | --- |
| `actions/checkout` | `v7` | Source checkout |
| `actions/setup-node` | `v7` | Native Node toolchain |
| `actions/setup-python` | `v7` | Python CI toolchain |
| `actions/upload-artifact` | `v7` | CI artifacts |
| `actions/download-artifact` | `v8` | Release artifacts |
| `softprops/action-gh-release` | `v3` | GitHub Release assets |

The PyPI publisher `pypa/gh-action-pypi-publish@release/v1` is a composite action and is retained. Its current implementation invokes a Node 24-capable `actions/setup-python` release when it needs to bootstrap Python.

## Automated guard

`scripts/check-actions-runtime.mjs` scans every workflow under `.github/workflows/` and rejects known deprecated Node 20 action major versions. It also verifies the repository's required action major lines remain consistent.

Run locally with:

```bash
pnpm actions:check
```

The guard is executed from the normal CI and both package publishing paths so action-runtime drift blocks verification before release.

## Scope

R17 changes CI infrastructure only. It does not change Native runtime semantics, Python runtime semantics, the DSH scheduler, recovery behavior, public API, or package contents.
