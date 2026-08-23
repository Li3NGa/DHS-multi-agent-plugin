import { defineConfig } from 'vitest/config'

/**
 * Real-DSH suites, run sequentially (each file owns a real harness):
 * - tests/integration: real runtime driving TypeScript sources
 * - tests/smoke: release artifacts — the package bundle and the ROOT
 *   dist/index.js entry that `dsh plugin add` mounts
 */
export default defineConfig({
  test: {
    include: ['tests/integration/**/*.spec.ts', 'tests/smoke/**/*.spec.ts'],
    testTimeout: 60_000,
    hookTimeout: 60_000,
    fileParallelism: false,
  },
})
