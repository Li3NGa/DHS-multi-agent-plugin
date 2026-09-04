# R13 Release Readiness

## Objective
Convert the verified Native runtime into a reproducible publishable package without changing runtime semantics.

## R13-01 Release contract
- Verify the public root package identity and publish configuration.
- Verify JavaScript and declaration entrypoints exist after build.
- Verify `cordis.patch.yml` is included as a release asset.
- Reject workspace/file/link dependency references that cannot be resolved by npm consumers.
- Enforce the supported Node baseline.

## R13-02 CI enforcement
- Run the release contract during the normal Native Runtime CI after the distributable build.
- Keep the npm publish workflow gated by the same contract.
- Preserve the existing source-of-truth, typecheck, unit, build, Real DSH, metadata, and consumer smoke gates.

## R13-03 Release decision
R13 passes only when the release contract is green in normal CI and the npm publish workflow contains the same hard gate. Publishing is not performed automatically by R13 development work.
