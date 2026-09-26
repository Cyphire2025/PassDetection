import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: { tsconfigPaths: true },
  test: {
    environment: "jsdom",
    // Each jsdom worker loads the application graph; bound concurrency on CI
    // and large-core developer hosts to avoid starving timed user workflows.
    maxWorkers: 2,
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**", ".next/**"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary", "lcov"],
      include: [
        "components/ui/modal.tsx",
        "components/layout/mobile-navigation.tsx",
        "features/auth/components/authenticated-content.tsx",
        "features/search/components/global-search.tsx",
        "features/documents/components/document-manual-review-dialog.tsx",
        "features/settings/components/dashboard-settings-page.tsx",
        "features/settings/components/appearance-settings.tsx",
        "lib/utils/coordinator-device-id.ts",
        "proxy.ts",
      ],
      thresholds: {
        perFile: true,
        statements: 74,
        branches: 50,
        functions: 75,
        lines: 75,
      },
    },
  },
});
