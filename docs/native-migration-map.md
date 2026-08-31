# Native Source Convergence Map

The migration from `dsh-native/` to `packages/dsh-multi-agent/` is complete for the production Native source tree.

## Authoritative mapping

| Historical tree | Production tree | Current role |
|---|---|---|
| `dsh-native/src/**` | `packages/dsh-multi-agent/src/**` | Legacy verification snapshot → production source |
| `dsh-native/tests/**` | `packages/dsh-multi-agent/tests/unit/**` | Historical tests → package unit tests |
| `dsh-native/smoke/dsh.smoke.spec.ts` | `packages/dsh-multi-agent/tests/integration/dsh.runtime.spec.ts` | Real-DSH integration coverage |
| `dsh-native/smoke/dsh.bundle.spec.ts` | `packages/dsh-multi-agent/tests/smoke/dsh.bundle.spec.ts` | Bundle artifact coverage |
| `dsh-native/smoke/planner.smoke.spec.ts` | `packages/dsh-multi-agent/tests/smoke/planner.smoke.spec.ts` | Planner + real DSH coverage |
| `dsh-native/smoke/e4-recovery.smoke.spec.ts` | `packages/dsh-multi-agent/tests/smoke/e4-recovery.smoke.spec.ts` | Recovery + real DSH coverage |
| `dsh-native/smoke/support.ts` | `packages/dsh-multi-agent/tests/smoke/support.ts` | Smoke harness support |

## Production path

Native production code is built only from:

```text
packages/dsh-multi-agent/src/index.ts
```

The repository root builds the installable release entry from that package source into:

```text
dist/index.js
```

The package itself builds:

```text
packages/dsh-multi-agent/dist/dsh.bundle.js
```

The authoritative Native workflow is:

```text
.github/workflows/native-runtime.yml
```

The former independent `dsh-native` workflow has been retired. This prevents two TypeScript CI signals from testing different copies of the Native implementation.

## Legacy snapshot

`dsh-native/` remains in the repository only until the final retirement gate is intentionally executed. The historical state is protected by:

```text
dhs-root-native-final
```

No new production code should be added under `dsh-native/`.

## Final retirement gate

Before deleting the legacy tree, verify all of the following on a clean checkout:

- production build does not read `dsh-native/`
- package tests do not import `dsh-native/`
- Native CI references only `packages/dsh-multi-agent/`
- root release entry is produced from the package source
- real-DSH bundle and root-entry smoke pass without the legacy tree
- package tarball/install succeeds without the legacy tree

Deleting the legacy tree is a repository hygiene change, not a runtime redesign.
