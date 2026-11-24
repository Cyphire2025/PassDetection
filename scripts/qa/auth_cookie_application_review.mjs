/** Real frontend auth modules over isolated loopback HTTP; all accounts/cookies synthetic. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve, sep, extname } from "node:path";
import { pathToFileURL } from "node:url";

const root = resolve(".");
const frontend = resolve(root, "frontend");
const require = createRequire(resolve(frontend, "package.json"));
const { chromium } = require("playwright");
const { build } = await import(pathToFileURL(require.resolve("vite")).href);
const workspace = resolve(root, ".tmp/auth-cookie-application");
const output = resolve(workspace, "dist");
await mkdir(workspace, { recursive: true });
await writeFile(resolve(workspace, "index.html"), '<!doctype html><title>Application auth transport fixture</title><script type="module" src="/entry.ts"></script>');
await writeFile(resolve(workspace, "entry.ts"), `
import { authApi } from "@/features/auth/api/auth.api";
import apiClient, { refreshAuthenticatedSession } from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth.store";
import { clearServerSessionCookies } from "@/features/auth/services/session-state";
import { coordinateCookieMutation } from "@/features/auth/services/cookie-mutation";
import { completeAuthenticationStepUp, STEP_UP_REQUIRED_EVENT } from "@/features/auth/services/step-up-coordinator";
const owner = (id) => ({ id, email: id + "@example.test", full_name: "Synthetic " + id,
 role: "agency_admin", agency_id: "agency-" + id, is_active: true, last_login_at: null,
 created_at: "2026-01-01", updated_at: "2026-01-01" });
window.audit = { authApi, apiClient, refreshAuthenticatedSession, clearServerSessionCookies, coordinateCookieMutation,
 setOwner(id) { useAuthStore.setState(s => ({ user: id ? owner(id) : null, isAuthenticated: !!id,
   hasHydrated: true, restorationStatus: id ? "authenticated" : "rejected", sessionVersion: s.sessionVersion + 1 })); },
 clearSession: () => useAuthStore.getState().clearSession("logout"),
 autoStepUp() { window.addEventListener(STEP_UP_REQUIRED_EVENT, () => {
   void authApi.stepUp("123456").then(completeAuthenticationStepUp);
 }); }, ready: true };
`);
await build({ configFile: false, root: workspace, logLevel: "error", resolve: { alias: { "@": frontend } },
  build: { outDir: output, emptyOutDir: false, sourcemap: true }, define: { "process.env.NODE_ENV": '"production"' } });

let configuration = {};
let records = [];
const user = (id) => ({ id, email: `${id}@example.test`, full_name: `Synthetic ${id}`, role: "agency_admin",
  agency_id: `agency-${id}`, is_active: true, last_login_at: null, created_at: "2026-01-01", updated_at: "2026-01-01" });
const server = createServer(async (request, response) => {
  const url = new URL(request.url, "http://127.0.0.1");
  const path = url.pathname;
  if (!path.startsWith("/api/")) {
    try {
      const asset = path === "/" || !extname(path) ? resolve(output, "index.html") : resolve(output, `.${path}`);
      if (!asset.startsWith(`${output}${sep}`)) { response.writeHead(404).end(); return; }
      response.setHeader("Content-Type", asset.endsWith(".js") ? "text/javascript" : asset.endsWith(".html") ? "text/html" : "application/octet-stream");
      response.end(await readFile(asset));
    } catch { response.writeHead(404).end(); }
    return;
  }
  let body = "";
  for await (const chunk of request) { body += chunk; if (body.length > 16_384) { response.writeHead(413).end(); return; } }
  const current = /audit_owner=([^;]+)/.exec(request.headers.cookie ?? "")?.[1] ?? null;
  const expected = request.headers["x-expected-actor-id"] ?? null;
  const local = { ...configuration };
  const record = { path, current, expected, status: null };
  records.push(record);
  response.setHeader("Content-Type", "application/json");
  response.setHeader("Cache-Control", "no-store");
  const finish = (status, data, cookieOwner) => {
    record.status = status;
    response.statusCode = status;
    if (cookieOwner !== undefined) response.setHeader("Set-Cookie", cookieOwner === null
      ? "audit_owner=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/"
      : `audit_owner=${cookieOwner}; HttpOnly; SameSite=Strict; Path=/`);
    response.end(status === 204 ? undefined : JSON.stringify(data));
  };
  if (local.delayPath === path) await new Promise((resolve) => setTimeout(resolve, 250));
  if (expected && current && expected !== current) {
    finish(409, { error: { code: "AUTH_REQUEST_OWNER_CHANGED", message: "Synthetic owner conflict" } }); return;
  }
  if (path === "/api/v1/auth/me") { finish(200, user(current)); return; }
  if (path === "/api/v1/auth/login") {
    const id = new URLSearchParams(body).get("username")?.startsWith("A") ? "A" : "B";
    if (local.challenge && id === "A") finish(200, { status: "mfa_required", challenge_token: "synthetic-challenge" }, null);
    else finish(200, { status: "authenticated", user: user(id) }, id);
  } else if (path === "/api/v1/auth/refresh" || path === "/api/v1/auth/mfa/step-up") {
    finish(200, { status: "authenticated", user: user(current), access_token_expires_at: "2099-01-01T00:00:00Z" }, current);
  } else if (path === "/api/v1/auth/logout") finish(204, null, null);
  else if (path === "/api/v1/auth/password/recovery/request") finish(200, { message: "Recovery requested" });
  else if (path === "/api/v1/auth/mfa/verify") finish(401, { error: { code: "INVALID_IDENTITY_PROOF", message: "Expired synthetic challenge" } });
  else if (path === "/api/v1/auth/password/change") {
    const attempt = records.filter((item) => item.path === path).length;
    if (attempt === 1) finish(403, { error: { code: "STEP_UP_REQUIRED" } });
    else finish(204, null, null);
  } else finish(200, { status: "authenticated", user: user("A") }, "A");
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true });
const results = [];
async function observed(path) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (records.some((item) => item.path === path)) return;
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error(`Synthetic transport not observed: ${path}`);
}
async function scenario(name, run, settings = {}) {
  records = []; configuration = settings;
  const context = await browser.newContext();
  await context.addCookies([{ name: "audit_owner", value: "A", url: origin, httpOnly: true }]);
  const first = await context.newPage(); const second = await context.newPage();
  for (const page of [first, second]) { await page.goto(origin); await page.waitForFunction(() => window.audit?.ready); }
  try { await run({ context, first, second }); results.push({ name, status: "passed", requests: records.map((item) => ({ ...item })) }); }
  catch (error) { results.push({ name, status: "failed", error: String(error), requests: records.map((item) => ({ ...item })) }); throw error; }
  finally { await context.close(); }
}
async function owner(page) { return page.evaluate(async () => (await window.audit.authApi.getMe()).id); }
try {
  await scenario("actual authApi later login follows earlier cookie writer", async ({ first, second }) => {
    const a = first.evaluate(() => window.audit.authApi.login({ email: "A@example.test", password: "SyntheticPass1" }));
    await observed("/api/v1/auth/login");
    const b = second.evaluate(() => window.audit.authApi.login({ email: "B@example.test", password: "SyntheticPass1" }));
    await Promise.all([a, b]); assert.equal(await owner(second), "B");
  }, { delayPath: "/api/v1/auth/login" });
  await scenario("actual challenge cookie deletion precedes later login", async ({ first, second }) => {
    const a = first.evaluate(() => window.audit.authApi.login({ email: "A@example.test", password: "SyntheticPass1" }));
    await observed("/api/v1/auth/login");
    const b = second.evaluate(() => window.audit.authApi.login({ email: "B@example.test", password: "SyntheticPass1" }));
    await Promise.all([a, b]); assert.equal(await owner(second), "B");
  }, { delayPath: "/api/v1/auth/login", challenge: true });
  await scenario("actual raw refresh finishes before queued later login", async ({ first, second }) => {
    await first.evaluate(() => window.audit.setOwner("A"));
    const refresh = first.evaluate(() => window.audit.refreshAuthenticatedSession());
    await observed("/api/v1/auth/refresh");
    const login = second.evaluate(() => window.audit.authApi.login({ email: "B@example.test", password: "SyntheticPass1" }));
    await Promise.all([refresh, login]); assert.equal(await owner(second), "B");
    assert.equal(records.find((item) => item.path.endsWith("refresh")).expected, "A");
  }, { delayPath: "/api/v1/auth/refresh" });
  await scenario("actual direct logout preserves initiating A while queued behind B", async ({ first, second }) => {
    await first.evaluate(() => window.audit.setOwner("A"));
    const login = second.evaluate(() => window.audit.authApi.login({ email: "B@example.test", password: "SyntheticPass1" }));
    await observed("/api/v1/auth/login");
    const logout = first.evaluate(() => window.audit.clearServerSessionCookies("A"));
    await Promise.all([login, logout]); assert.equal(await owner(second), "B");
    assert.equal(records.find((item) => item.path.endsWith("logout")).status, 409);
  }, { delayPath: "/api/v1/auth/login" });
  await scenario("actual stale queued raw refresh is rejected without retry", async ({ first, second }) => {
    await first.evaluate(() => window.audit.setOwner("A"));
    const login = second.evaluate(() => window.audit.authApi.login({ email: "B@example.test", password: "SyntheticPass1" }));
    await observed("/api/v1/auth/login");
    const refresh = first.evaluate(() => window.audit.refreshAuthenticatedSession().then(() => null, (error) => error.code));
    await login; assert.equal(await refresh, "AUTH_REQUEST_OWNER_CHANGED");
    assert.equal(await owner(second), "B");
    assert.equal(records.filter((item) => item.path.endsWith("refresh")).length, 1);
  }, { delayPath: "/api/v1/auth/login" });
  await scenario("actual MFA proof failure does not refresh unrelated staff cookies", async ({ first }) => {
    await first.evaluate(() => window.audit.setOwner("A"));
    const code = await first.evaluate(() => window.audit.authApi.verifyMfa("expired", "123456").then(() => null, (error) => error.code));
    assert.equal(code, "INVALID_IDENTITY_PROOF");
    assert.equal(records.some((item) => item.path.endsWith("refresh")), false);
    assert.equal(await owner(first), "A");
  });
  await scenario("actual password-change step-up releases and reacquires transport lock", async ({ first }) => {
    await first.evaluate(() => { window.audit.setOwner("A"); window.audit.autoStepUp(); });
    await first.evaluate(() => window.audit.authApi.changePassword("ExistingPass1", "ReplacementPass1"));
    assert.deepEqual(records.map((item) => item.path), ["/api/v1/auth/password/change", "/api/v1/auth/mfa/step-up", "/api/v1/auth/password/change"]);
  });
  await scenario("actual missing-capability failure is actionable and public recovery remains available", async ({ first }) => {
    const result = await first.evaluate(async () => {
      Object.defineProperty(navigator, "locks", { configurable: true, value: undefined });
      const error = await window.audit.authApi.login({ email: "A@example.test", password: "SyntheticPass1" }).then(() => null, (error) => ({ code: error.code, message: error.message }));
      const recovery = await window.audit.authApi.requestPasswordRecovery("A@example.test");
      return { error, recovery };
    });
    assert.equal(result.error.code, "AUTH_COOKIE_COORDINATION_UNAVAILABLE");
    assert.match(result.error.message, /Use HTTPS or localhost/);
    assert.equal(result.recovery.message, "Recovery requested");
    assert.equal(records.some((item) => item.path.endsWith("login")), false);
  });
  await scenario("actual native queued identity lock is cancelled on local actor change", async ({ first }) => {
    await first.evaluate(() => {
      window.audit.setOwner("A");
      window.audit.holder = window.audit.coordinateCookieMutation(() => new Promise((resolve) => { window.audit.release = resolve; }));
    });
    await first.waitForFunction(() => typeof window.audit.release === "function");
    const pending = first.evaluate(() => window.audit.authApi.activate("synthetic-token", "SyntheticPass1").then(() => null, (error) => error.code));
    await first.waitForFunction(async () => (await navigator.locks.query()).pending.some((lock) => lock.name === "passdetection-auth-cookie-writer"));
    await first.evaluate(() => { window.audit.setOwner("B"); window.audit.release(); });
    assert.ok(await pending);
    await first.evaluate(() => window.audit.holder);
    assert.equal(records.some((item) => item.path.endsWith("activate")), false);
  });
  await scenario("actual voluntary logout navigation retains a completed server logout", async ({ first, second }) => {
    await first.evaluate(() => window.audit.setOwner("A"));
    await Promise.all([first.waitForURL(`${origin}/login`), first.evaluate(() => { void window.audit.clearSession(); })]);
    await new Promise((resolve) => setTimeout(resolve, 400));
    assert.equal(records.find((item) => item.path.endsWith("logout"))?.status, 204);
    const cookies = await second.context().cookies();
    assert.equal(cookies.some((item) => item.name === "audit_owner"), false);
  }, { delayPath: "/api/v1/auth/logout" });
  await scenario("actual logout full navigation cannot release its lock before late headers clear B", async ({ first, second }) => {
    await first.evaluate(() => window.audit.setOwner("A"));
    await Promise.all([first.waitForURL(`${origin}/login`), first.evaluate(() => { void window.audit.clearSession(); })]);
    await second.evaluate(() => window.audit.authApi.login({ email: "B@example.test", password: "SyntheticPass1" }));
    await new Promise((resolve) => setTimeout(resolve, 400));
    assert.equal(await owner(second), "B");
  }, { delayPath: "/api/v1/auth/logout" });
} finally {
  const sources = ["frontend/lib/api/client.ts", "frontend/lib/api/request-owner.ts", "frontend/stores/auth.store.ts", "frontend/features/auth/api/auth.api.ts", "frontend/features/auth/services/cookie-mutation.ts", "frontend/features/auth/services/session-state.ts"];
  const source_sha256 = Object.fromEntries(await Promise.all(sources.map(async (path) => [path, createHash("sha256").update(await readFile(resolve(root, path))).digest("hex")])));
  await writeFile(resolve(root, "docs/audit/dashboard-2026-10-30/auth-cookie-application-browser.json"), `${JSON.stringify({
    browser: browser.version(), source_sha256, results,
    scope: "Actual frontend authApi, Axios adapters/interceptors, refresh coordinator, store and logout source bundled by installed Vite, running in real Chromium over loopback. HTTP backend/accounts/cookies are synthetic; actual backend preconditions separately verified by ASGI/durable SQLite tests. No deployed/full Next UI or PostgreSQL/provider certification.",
  }, null, 2)}\n`);
  await browser.close(); await new Promise((resolve) => server.close(resolve));
}
console.log(`${results.length} actual-module browser scenarios passed.`);
