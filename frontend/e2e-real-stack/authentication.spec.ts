import { createHmac } from "node:crypto";
import { expect, test } from "@playwright/test";

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
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login(?:\?.*)?$/);
  expect((await context.request.get("/api/v1/auth/me")).status()).toBe(401);
  expect((await context.cookies()).some(cookie => cookie.name === "refresh_token")).toBe(false);
});
