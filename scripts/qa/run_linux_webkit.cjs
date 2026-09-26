/* Isolated Linux WebKit qualification; TLS bytes pass through unchanged.
 * Run only inside the official, version-matched Playwright image, sharing the
 * disposable qualification Nginx network namespace. No Docker socket required.
 */
const net = require("node:net");
const fs = require("node:fs");
const { spawn } = require("node:child_process");
const { webkit } = require("/workspace/frontend/node_modules/playwright");

if (process.env.QUALIFICATION_PROJECT !== "passdetection-qualification") {
  throw new Error("Only the isolated qualification project is allowed");
}
const connections = new Set();
const forward = net.createServer((client) => {
  const upstream = net.connect(443, "127.0.0.1");
  for (const socket of [client, upstream]) {
    connections.add(socket);
    socket.on("close", () => connections.delete(socket));
    socket.on("error", () => { client.destroy(); upstream.destroy(); });
  }
  client.pipe(upstream).pipe(client);
});
function finish(code) {
  for (const socket of connections) socket.destroy();
  forward.close(() => process.exit(code));
}
forward.on("error", (error) => { console.error(error.message); process.exit(1); });
forward.listen(58443, "127.0.0.1", async () => {
  let browser;
  try {
    browser = await webkit.launch();
    const page = await browser.newPage({ ignoreHTTPSErrors: true });
    await page.goto("https://localhost:58443/login");
    const capabilities = await page.evaluate(async () => {
      let ed25519 = false;
      try { ed25519 = Boolean(await crypto.subtle.generateKey({ name: "Ed25519" }, false, ["sign", "verify"])); } catch {}
      return { secureContext: isSecureContext, mediaDevices: typeof navigator.mediaDevices === "object", canvasCaptureStream: typeof HTMLCanvasElement.prototype.captureStream === "function", ed25519 };
    });
    fs.writeFileSync("/evidence/capabilities.json", JSON.stringify(capabilities, null, 2));
    await browser.close(); browser = null;
    if (Object.values(capabilities).some((value) => value !== true)) throw new Error("Linux WebKit lacks required real browser capability");
    const child = spawn(process.execPath, ["node_modules/playwright/cli.js", "test", "--config=playwright.real-stack.config.ts", "scanner-offline.spec.ts", "--project=webkit", "--output=/evidence/results", "--reporter=list"], {
      cwd: "/workspace/frontend", stdio: "inherit", env: { ...process.env, RUN_REAL_STACK: "1", REAL_STACK_BASE_URL: "https://localhost:58443" },
    });
    const timeout = setTimeout(() => child.kill("SIGTERM"), 180_000);
    child.on("error", () => { clearTimeout(timeout); finish(1); });
    child.on("exit", (code) => { clearTimeout(timeout); finish(code ?? 1); });
  } catch (error) {
    console.error(error.message);
    if (browser) await browser.close();
    finish(1);
  }
});
