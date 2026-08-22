import { defineConfig } from 'vitest/config'

/**
 * Root package tests ONLY. The dsh-native/ runtime owns its own suites
 * (vitest.config.ts + vitest.smoke.config.ts inside dsh-native/); without
 * this include filter the root runner sweeps them too and the two native
 * CI signals bleed into each other during the convergence transition.
 */
export default defineConfig({
  test: {
    include: ['tests/**/*.spec.ts'],
    environment: 'node',
  },
})
