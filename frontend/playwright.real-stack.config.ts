import { defineConfig, devices } from "@playwright/test";

if (process.env.RUN_REAL_STACK !== "1") {
  throw new Error("Real-stack qualification requires RUN_REAL_STACK=1 and an isolated stack.");
}
const baseURL = process.env.REAL_STACK_BASE_URL ?? "https://localhost:58443";
const origin = new URL(baseURL);
if (!['localhost', '127.0.0.1'].includes(origin.hostname) || origin.protocol !== 'https:') {
  throw new Error("Real-stack qualification is restricted to a local HTTPS target.");
}

export default defineConfig({
  testDir: "./e2e-real-stack",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  forbidOnly: Boolean(process.env.CI),
  reporter: [["list"], ["html", { outputFolder: "real-stack-report", open: "never" }]],
  outputDir: "real-stack-results",
  use: { baseURL, ignoreHTTPSErrors: true, trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
});
