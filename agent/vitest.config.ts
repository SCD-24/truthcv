import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: [
      'harness/**/*.test.ts',
      'harness/**/__tests__/**/*.ts',
    ],
    coverage: {
      provider: 'v8',
      reporter: ['text'],
      include: ['harness/**/*.ts'],
      exclude: ['harness/**/__tests__/**', 'harness/**/*.test.ts'],
    },
  },
});
