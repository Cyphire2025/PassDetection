import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: { tsconfigPaths: true },
  test: {
    environment: "jsdom",
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
        "features/passports/components/passport-retention-control.tsx",
        "features/search/components/global-search.tsx",
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
