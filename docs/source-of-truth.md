# Native Source of Truth

## Scope

This repository contains two production runtimes with different responsibilities:

- **Python Runtime**: `src/deepseek_multi_agent_plugin/`
- **Native DSH Runtime**: `packages/dsh-multi-agent/`

They are not duplicate build targets. The Python runtime remains the compatibility/reference runtime for the Python API, CLI, HTTP and MCP surface. The Native DSH runtime is the only production source tree for the DSH/Cordis plugin.

## Native rule

For Native code, the production source of truth is:

```text
packages/dsh-multi-agent/src/
```

This is the sole authoritative Native source tree. The historical `dsh-native/` verification snapshot has been retired (see `docs/native-migration-map.md`).

## Retirement completed (2026-09-04)

All retirement gates have been verified and the legacy `dsh-native/` tree has been removed:

1. `packages/dsh-multi-agent` builds and typechecks independently. ✅
2. Unit, integration and real-DSH smoke suites run from the package source tree. ✅
3. The release entry at `dist/index.js` is built from `packages/dsh-multi-agent/src/index.ts`. ✅
4. `dsh plugin add` installation metadata points to the package-produced release artifact. ✅
5. Repository CI has exactly one authoritative Native runtime workflow (`native-runtime.yml`). ✅
6. No production source, test, build script or documentation imports `dsh-native`. ✅
7. A clean checkout can install and load the Native package without the legacy tree. ✅

## Release flow

```text
packages/dsh-multi-agent/src
        ↓
package build
        ↓
root dist/index.js
        ↓
Cordis / DSH plugin loading
        ↓
Real DSH smoke
```

The Python runtime follows its own release/test flow and is not used to satisfy Native runtime verification.
