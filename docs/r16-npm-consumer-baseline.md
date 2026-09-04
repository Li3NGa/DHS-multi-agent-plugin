# R16 npm Consumer Baseline

## Objective

Verify the published Native package the way a real npm consumer installs it, using the supported Node baseline rather than only exercising the monorepo through pnpm.

## Consumer gate

The Native Runtime CI now:

1. builds the release entry;
2. runs `npm pack` to create the exact tarball that would be published;
3. creates a clean consumer project with `npm init`;
4. installs that tarball with `npm install`;
5. imports `dhs-multi-agent` from the installed package;
6. compiles a TypeScript consumer against the published declaration entrypoint.

This catches packaging, export-map, dependency, and declaration issues that a workspace-local test can miss.

## Release baseline

The npm publish workflow now uses Node.js `22.14.0`, matching the package's declared minimum engine baseline.

The publish workflow remains separate from the Python PyPI workflow and continues to require the source-of-truth, typecheck, unit, build, release metadata, release contract, Public API, and public product surface gates before publication.
