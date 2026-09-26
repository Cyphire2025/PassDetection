import { createHmac, randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

// This spec injects a malformed read response; SW coverage belongs to scanner.
test.use({ serviceWorkers: "block" });

// Synthetic accounts only, created by scripts/qa/seed_enterprise_browser_stack.py.
// One account per browser avoids treating legitimate TOTP replay rejection as flakiness.
const accounts: Record<string, { email: string; secret: string }> = {
  chromium: { email: "enterprise.browser.chromium@example.test", secret: "JBSWY3DPEHPK3PXP" },
  firefox: { email: "enterprise.browser.firefox@example.test", secret: "GEZDGNBVGY3TQOJQ" },
  webkit: { email: "enterprise.browser.webkit@example.test", secret: "KRSXG5DSNFXGOIDB" },
};

function totp(secret: string): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const bits = [...secret].map(char => alphabet.indexOf(char).toString(2).padStart(5, "0")).join("");
  const key = Buffer.from(bits.match(/.{8}/g)!.map(byte => parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000)));
  const digest = createHmac("sha1", key).update(counter).digest();
  const offset = digest[digest.length - 1] & 15;
  return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

test("real TLS login, MFA, persistence, CSRF, refresh, deep links and logout", async ({ page, context }, info) => {
  const account = accounts[info.project.name];
  await page.goto("/login?from=%2Fdashboard");
  await page.getByLabel("Email address").fill(account.email);
  await page.locator("#login-password").fill("Enterprise-Browser-QA-937!");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByLabel("Verification code")).toBeVisible();
  await page.getByLabel("Verification code").fill(totp(account.secret));
  const sessionResponse = page.waitForResponse(response => response.url().endsWith("/api/v1/auth/mfa/verify") && response.request().method() === "POST");
  // The dashboard hydrator rotates the session on mount. Let the real browser
  // finish that coordinated renewal before this test issues its own API probe;
  // otherwise the harness races a stale refresh cookie outside the app's lock.
  const dashboardRenewal = page.waitForResponse(response => response.url().endsWith("/api/v1/auth/refresh") && response.status() === 200);
  await page.getByRole("button", { name: "Verify", exact: true }).click();
  const setCookies = (await (await sessionResponse).headersArray())
    .filter(header => header.name.toLowerCase() === "set-cookie").map(header => header.value);
  await expect(page).toHaveURL(/\/dashboard$/);
  await dashboardRenewal;
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  const cookies = await context.cookies();
  for (const name of ["access_token", "refresh_token"]) {
    const cookie = cookies.find(candidate => candidate.name === name);
    expect(cookie, `${name} persisted by the real backend`).toBeDefined();
    expect(cookie!.httpOnly).toBe(true);
    expect(cookie!.secure).toBe(true);
    // WebKit on Windows does not reliably expose SameSite through the browser
    // inspection protocol. Verify the wire contract on the real TLS response.
    expect(setCookies.find(header => header.startsWith(`${name}=`))).toMatch(/;\s*SameSite=Lax/i);
  }
  const me = await context.request.get("/api/v1/auth/me");
  expect(me.status()).toBe(200);
  expect((await me.json()).email).toBe(account.email);
  const rejected = await context.request.post("/api/v1/auth/refresh", {
    headers: { Origin: "https://untrusted.example" }, data: {},
  });
  expect(rejected.status()).toBe(403);
  const refresh = await context.request.post("/api/v1/auth/refresh", {
    headers: { Origin: new URL(page.url()).origin }, data: {},
  });
  expect(refresh.status()).toBe(200);
  await page.reload();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await page.goto("/dashboard?qualification=deep-link");
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await test.step("feature dialog traps keyboard focus and restores its trigger", async () => {
    await page.goto("/upload-links");
    const trigger = page.getByRole("button", { name: "Create Group Link", exact: true }).first();
    await trigger.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("[data-dialog-initial-focus]")).toBeFocused();
    for (const key of ["Shift+Tab", "Tab"]) {
      for (let index = 0; index < 24; index += 1) {
        await page.keyboard.press(key);
        expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true);
      }
    }
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });
  await test.step("controlled render fault reports metadata to the real collector", async () => {
    // Fault injection at this single read response; the collector, TLS, auth and
    // remaining application services are real. No exception text is transmitted.
    await page.route("**/api/v1/dashboard/stats", async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...await response.json(), recent_submissions: { length: 1, secret: "synthetic-private-marker" } } });
    });
    const report = page.waitForResponse((response) => response.url().endsWith("/observability/frontend-errors"));
    await page.goto("/dashboard?private_query=synthetic-private-marker");
    const accepted = await report;
    expect(accepted.status()).toBe(202);
    const metadata = accepted.request().postDataJSON();
    expect(Object.keys(metadata).sort()).toEqual(["boundary", "error_kind", "event_id", "fingerprint", "release", "route"]);
    expect(metadata.route).toBe("/dashboard");
    expect(JSON.stringify(metadata)).not.toContain("synthetic-private-marker");
    const receipt = await accepted.json();
    await expect(page.getByText(`Support reference: ${receipt.event_id}`, { exact: true })).toBeVisible();
    const frontendId = execFileSync("docker", ["compose", "--env-file", "../.env.example", "-p", "passdetection-qualification", "-f", "../docker-compose.qualification.yml", "ps", "-q", "frontend"], { encoding: "utf8", timeout: 15_000 }).trim();
    const artifactRevision = execFileSync("docker", ["inspect", "--format", '{{index .Config.Labels "org.opencontainers.image.revision"}}', frontendId], { encoding: "utf8", timeout: 15_000 }).trim();
    const expectedRevision = process.env.QUALIFICATION_REVISION ?? process.env.GITHUB_SHA ?? artifactRevision;
    expect(expectedRevision).toMatch(/^[A-Za-z0-9._-]{1,64}$/);
    expect(expectedRevision).not.toBe("unknown");
    expect(artifactRevision).toBe(expectedRevision);
    expect(metadata.release).toBe(expectedRevision);
    const duplicate = await context.request.post("/api/v1/observability/frontend-errors", {
      headers: { Origin: new URL(page.url()).origin },
      data: { ...metadata, event_id: randomUUID() },
    });
    expect(duplicate.status()).toBe(202);
    expect((await duplicate.json()).event_id).toBe(receipt.event_id);
    const logs = execFileSync("docker", ["compose", "--env-file", "../.env.example", "-p", "passdetection-qualification", "-f", "../docker-compose.qualification.yml", "logs", "--no-color", "backend", "--tail", "3000"], { encoding: "utf8", timeout: 15_000 });
    const records = logs.split(/\r?\n/).filter((line) => line.includes("frontend_render_failure") && line.includes(receipt.event_id));
    expect(records).toHaveLength(1);
    expect(records[0]).toContain(metadata.fingerprint);
    expect(records[0]).toContain(metadata.release);
    expect(records[0]).toContain(metadata.route);
    expect(records[0]).not.toContain("synthetic-private-marker");
    writeFileSync(info.outputPath("frontend-error-receipt.json"), JSON.stringify({ browser: info.project.name, metadata, receipt, duplicate_returns_original_id: true, matching_structured_log_records: records.length, private_marker_absent: true }, null, 2));
    await page.unroute("**/api/v1/dashboard/stats");
    await page.reload();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  });
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login(?:\?.*)?$/);
  expect((await context.request.get("/api/v1/auth/me")).status()).toBe(401);
  expect((await context.cookies()).some(cookie => cookie.name === "refresh_token")).toBe(false);
});
