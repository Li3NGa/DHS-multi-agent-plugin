# Native Source of Truth

## Scope

This repository currently contains two production runtimes with different responsibilities:

- **Python Runtime**: `src/deepseek_multi_agent_plugin/`
- **Native DSH Runtime**: `packages/dsh-multi-agent/`

They are not duplicate build targets. The Python runtime remains the compatibility/reference runtime for the Python API, CLI, HTTP and MCP surface. The Native DSH runtime is the only production source tree for the DSH/Cordis plugin.

## Native rule

For Native code, the production source of truth is:

```text
packages/dsh-multi-agent/src/
```

The following tree is **legacy verification/snapshot material only**:

```text
dsh-native/
```

It must not be used by the Native release pipeline, package exports, or production documentation.

## Evidence for retirement

The legacy tree is protected by the remote snapshot tag:

```text
dhs-root-native-final
```

Its retirement gate is:

1. `packages/dsh-multi-agent` builds and typechecks independently.
2. Unit, integration and real-DSH smoke suites run from the package source tree.
3. The release entry at `dist/index.js` is built from `packages/dsh-multi-agent/src/index.ts`.
4. `dsh plugin add` installation metadata points to the package-produced release artifact.
5. Repository CI has exactly one authoritative Native runtime workflow.
6. No production source, test, build script or documentation imports `dsh-native`.
7. A clean checkout can install and load the Native package without the legacy tree.

Until all gates are proven, `dsh-native/` must not be deleted or used as a second implementation.

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
