# R15 Native Product Surface

## Objective

Keep the repository and published npm package aligned around the Native DSH product without deleting or rewriting the existing Python runtime.

## Contract

The root public surface must:

- identify `dhs-multi-agent` as the Native DSH/Cordis package;
- provide an npm installation path and Node.js `>=22.14.0` baseline;
- point users at `packages/dsh-multi-agent/src/` as the Native production source;
- expose the `ctx.multiAgent` Cordis integration in the primary usage path;
- avoid stale Python-first CI/PyPI badges in the root product documentation;
- retain a clear pointer to the separate Python runtime under `src/deepseek_multi_agent_plugin/`.

## Enforcement

`scripts/check-public-surface.mjs` validates the root README and package metadata. It runs through `pnpm surface:check` in both the Native Runtime CI and the npm publish workflow.

This is intentionally a documentation/package-surface guard rather than a runtime semantic change.

## Release implication

A Native release is not considered product-ready when the implementation is correct but the public package surface is misleading or points to the wrong runtime. R15 therefore treats documentation identity as a release contract.
