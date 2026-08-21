import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'node',
    // the runtime is fully deterministic (no sleeps, no random delays);
    // fake timers drive timeout/cancellation tests
    testTimeout: 10_000,
  },
})
