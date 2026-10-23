import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

// Build with the same isolated loopback API origins before production measurements.
const production = process.env.HOLOGRAM_PRODUCTION === "1";
const webkit = process.env.HOLOGRAM_WEBKIT === "1";
export default defineConfig({
  ...base,
  testMatch: webkit ? ["**/ai-hologram-compatibility.spec.ts"] : ["**/ai-hologram-*.spec.ts", "**/ai-assistant-test-hologram.spec.ts", "**/ai-test-landscape-controls.spec.ts", "**/ai-test-hologram-idle.spec.ts", "**/ai-test-hologram-flow.spec.ts"],
  workers: 1,
  projects: webkit ? [{ name: "webkit", use: { browserName: "webkit" } }] : base.projects,
  use: { ...base.use, launchOptions: !webkit && process.env.HOLOGRAM_HARDWARE === "1" ? { args: ["--use-gl=angle", "--use-angle=d3d11", "--enable-gpu"] } : {} },
  webServer: (base.webServer as Array<{ command: string }>).map((server) => ({
    ...server,
    command: production ? server.command.replace("npm run dev", "npm run start") : server.command,
  })),
});
