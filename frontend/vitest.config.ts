import { defineConfig, mergeConfig } from 'vitest/config';
import viteConfig from './vite.config.ts';

// Extends the app's own config so tests see the same build-time values (version) and file access as the real build.
export default mergeConfig(viteConfig, defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      reportsDirectory: './coverage',
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/test/**',
        'src/main.tsx',
        'src/vite-env.d.ts',
        '**/*.d.ts',
      ],
      thresholds: {
        // UI components (Canvas, NodeComponent, App) are covered by E2E tests,
        // not unit tests — thresholds reflect unit-testable business logic only.
        lines: 22,
        functions: 30,
        branches: 28,
        statements: 22,
      },
    },
  },
}));
