import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e-fixtures",
  workers: 1,
  retries: 0,
  timeout: 20_000,
  forbidOnly: Boolean(process.env.CI),
  reporter: "list",
  outputDir: "fixture-results",
  use: { trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [{ name: "webkit", use: { ...devices["Desktop Safari"] } }],
});
