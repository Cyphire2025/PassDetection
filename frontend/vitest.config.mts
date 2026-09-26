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
        "components/ui/modal-keyboard-boundary.ts",
        "components/ui/modal-focus-return.tsx",
        "components/shared/error-boundary.tsx",
        "lib/navigation/application-route.ts",
        "lib/observability/render-errors.ts",
        "features/auth/services/refresh-attempt.ts",
        "features/upload/services/passport-capture-transition.ts",
        "features/upload/services/saved-passport-extraction.ts",
        "features/upload/services/upload-operation-state.ts",
        "features/upload/services/family-upload-state.ts",
        "features/upload/services/review-submission-validation.ts",
        "features/upload/hooks/use-upload-operation.ts",
        "features/upload/hooks/use-upload-family.ts",
        "features/upload/hooks/use-upload-documents.ts",
        "features/upload/hooks/use-upload-submission.ts",
        "features/upload/components/upload-review-panels.tsx",
        "features/passports/components/use-passport-detail-navigation.ts",
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
