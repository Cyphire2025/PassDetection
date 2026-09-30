import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

// Worktrees share an installed node_modules outside the Turbopack root. This
// bounded browser check uses the supported webpack dev mode and keeps the
// original isolated API destinations and no-server-reuse policy.
export default defineConfig({
  ...base,
  testMatch: "mcp-read-only.spec.ts",
  workers: 1,
  webServer: (Array.isArray(base.webServer) ? base.webServer : [base.webServer]).map((server) => {
    if (!server) throw new Error("The isolated browser server configuration is missing.");
    return server.command.startsWith("npm run dev") ? { ...server, command: `${server.command} --webpack` } : server;
  }),
});
