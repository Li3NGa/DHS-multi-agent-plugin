import { defineConfig } from 'vitest/config'

/**
 * Real-DSH smoke suite: boots the actual harness (cordis + dsh services)
 * per file. Keep files sequential: each owns a real runtime.
 */
export default defineConfig({
  test: {
    include: ['smoke/**/*.spec.ts'],
    testTimeout: 60_000,
    hookTimeout: 60_000,
    fileParallelism: false,
  },
})
