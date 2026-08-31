# Legacy Native Verification Snapshot

> **Legacy / verification only.** This directory is no longer the production Native source tree.
>
> Production Native source of truth: `packages/dsh-multi-agent/src/`
>
> Historical verification snapshot is protected by the remote tag:
>
> ```text
> dhs-root-native-final
> ```

## Why this directory remains

The files under `dsh-native/` document and preserve the first real-DSH verification work used to align the plugin with the DeepSeek Harness runtime. They remain useful for historical comparison and audit, but they are deliberately excluded from the authoritative Native CI and release path.

Do **not** add new production code here.

## Production commands

Use the repository root / package workspace instead:

```bash
pnpm install --frozen-lockfile
pnpm --dir packages/dsh-multi-agent typecheck
pnpm --dir packages/dsh-multi-agent test
pnpm --dir packages/dsh-multi-agent build
pnpm test:smoke
```

## Retirement rule

The legacy directory can be removed only after `docs/source-of-truth.md` retirement gates are satisfied and a clean checkout proves that package build, root release entry and real-DSH smoke are independent of this directory.
