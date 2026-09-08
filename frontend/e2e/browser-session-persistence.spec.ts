import { chromium, expect, test, type BrowserContext, type Route } from "@playwright/test";
import { E2E_APP_PORT } from "../config/e2e-isolation";

const user = {
  id: "session-test-admin", email: "session@example.test", full_name: "Session Test Admin",
  role: "agency_admin", agency_id: "session-test-agency", is_active: true, capabilities: [],
  last_login_at: null, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z",
};
const session = {
  status: "authenticated", user, token_type: "bearer",
  access_token_expires_at: new Date(Date.now() + 600_000).toISOString(),
};
const persistentCookie = "refresh_token=verified-browser-session; Max-Age=604800; Path=/api/v1/auth; HttpOnly; SameSite=Lax";
const accessCookie = "access_token=verified-access; Max-Age=600; Path=/; HttpOnly; SameSite=Lax";

async function json(route: Route, body: unknown, status = 200, cookie?: string) {
  await route.fulfill({
    status, contentType: "application/json", body: JSON.stringify(body),
    headers: cookie ? { "set-cookie": cookie } : undefined,
  });
}

function authFixture() {
  let refreshStatus = 200;
  let loginRequests = 0;
  let mfaRequests = 0;
  let refreshRequests = 0;
  let revoked = false;
  const requests: string[] = [];

  async function install(context: BrowserContext) {
    await context.route("**/api/v1/**", async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      requests.push(path);
      if (path === "/api/v1/auth/refresh") {
        refreshRequests += 1;
        if (refreshStatus >= 500) return json(route, { error: { code: "TEMPORARILY_UNAVAILABLE", message: "Retry shortly." } }, refreshStatus);
        const hasCookie = request.headers().cookie?.includes("refresh_token=verified-browser-session");
        if (revoked || !hasCookie || refreshStatus === 401) return json(route, {
          error: { code: "AUTH_REFRESH_REJECTED", message: "The verified session ended." },
        }, 401, "refresh_token=; Max-Age=0; Path=/api/v1/auth; HttpOnly; SameSite=Lax");
        return json(route, session, 200, accessCookie);
      }
      if (path === "/api/v1/auth/login") {
        loginRequests += 1;
        return json(route, {
          status: "mfa_required", challenge_token: "isolated-authenticator-challenge",
          expires_at: new Date(Date.now() + 300_000).toISOString(), setup_secret: null, otpauth_uri: null,
        });
      }
      if (path === "/api/v1/auth/mfa/verify") {
        mfaRequests += 1;
        expect(request.postDataJSON()).toEqual({ challenge_token: "isolated-authenticator-challenge", code: "123456" });
        revoked = false;
        return json(route, session, 200, persistentCookie);
      }
      if (path === "/api/v1/auth/me") return json(route, user);
      if (path === "/api/v1/auth/logout") {
        revoked = true;
        return json(route, { message: "Signed out" }, 200,
          "refresh_token=; Max-Age=0; Path=/api/v1/auth; HttpOnly; SameSite=Lax");
      }
      if (path === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
      if (path === "/api/v1/dashboard/stats") return json(route, {
        total_passports: 0, pending_review: 0, confirmed: 0, active_links: 0, recent_submissions: [],
      });
      return json(route, request.method() === "GET" ? [] : {});
    });
  }
  return {
    install,
    setRefreshStatus(status: number) { refreshStatus = status; },
    counts: () => ({ loginRequests, mfaRequests, refreshRequests }),
    requests,
  };
}

async function addSavedSession(context: BrowserContext) {
  await context.addCookies([{
    name: "refresh_token", value: "verified-browser-session", domain: "127.0.0.1", path: "/api/v1/auth",
    expires: Math.floor(Date.now() / 1000) + 7 * 24 * 60 * 60, httpOnly: true, sameSite: "Lax",
  }]);
}

test("verified session survives a real browser close and reopen without repeating password or MFA", async ({}, testInfo) => {
  const profile = testInfo.outputPath("persistent-browser-profile");
  const options = { headless: true, baseURL: `http://127.0.0.1:${E2E_APP_PORT}`, viewport: { width: 1280, height: 800 } };
  const fixture = authFixture();
  let context = await chromium.launchPersistentContext(profile, options);
  try {
    await fixture.install(context);
    let page = context.pages()[0] ?? await context.newPage();
    await page.goto("/login?from=%2Fdashboard");
    await page.getByLabel("Email address").fill(user.email);
    await page.locator("#login-password").fill("SyntheticTestPassword9!");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Verify your identity" })).toBeVisible();
    await page.getByLabel("Verification code").fill("123456");
    await page.getByRole("button", { name: "Verify", exact: true }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    const cookie = (await context.cookies()).find(item => item.name === "refresh_token")!;
    expect(cookie.httpOnly).toBe(true);
    expect(cookie.expires).toBeGreaterThan(Date.now() / 1000 + 6 * 24 * 60 * 60);
    // Only persistent, backend-owned cookies can carry this restart. Access
    // expiry and cleared localStorage must not require a second authenticator.
    await context.clearCookies({ name: "access_token" });
    await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
    await context.close();
    context = await chromium.launchPersistentContext(profile, options);
    await fixture.install(context);
    page = context.pages()[0] ?? await context.newPage();
    await page.goto("/");
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    expect(fixture.counts()).toMatchObject({ loginRequests: 1, mfaRequests: 1 });
    await expect(page.getByLabel("Verification code")).toHaveCount(0);
  } finally {
    await context.close();
  }
});

test("a saved session restores a bookmarked login destination and cookie clearing brings back sign in", async ({ context, page }) => {
  const fixture = authFixture();
  await fixture.install(context);
  await addSavedSession(context);
  await page.goto("/login?from=%2Fpassports%3Fview%3Ddocs");
  await expect(page).toHaveURL(/\/passports\?view=docs$/);
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  expect(fixture.counts()).toMatchObject({ loginRequests: 0, mfaRequests: 0 });
  await context.clearCookies();
  await page.goto("/login");
  await expect(page.getByLabel("Email address")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
});

test("expired or revoked refresh requires sign in and keeps the original return destination", async ({ context, page }) => {
  const fixture = authFixture();
  fixture.setRefreshStatus(401);
  await fixture.install(context);
  await addSavedSession(context);
  await page.goto("/session-restore?from=%2Fpassports%3Fview%3Ddocs");
  await expect(page).toHaveURL(/\/login\?reason=session_expired&from=%2Fpassports%3Fview%3Ddocs$/);
  await expect(page.getByLabel("Email address")).toBeVisible();
  expect(fixture.counts()).toMatchObject({ loginRequests: 0, mfaRequests: 0 });
});

test("a temporary refresh outage offers retry and recovers the existing verified session", async ({ context, page }) => {
  const fixture = authFixture();
  fixture.setRefreshStatus(503);
  await fixture.install(context);
  await addSavedSession(context);
  await page.goto("/login");
  await expect(page.getByRole("alert").filter({ hasText: "Let’s reconnect." })).toHaveText(/checked once the connection is back/);
  await expect(page.getByLabel("Email address")).toHaveCount(0);
  fixture.setRefreshStatus(200);
  await page.getByRole("button", { name: "Retry connection" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  expect(fixture.counts()).toMatchObject({ loginRequests: 0, mfaRequests: 0 });
});

test("sign out ends saved access and preserves password recovery and account switching", async ({ context, page }) => {
  const fixture = authFixture();
  await fixture.install(context);
  await addSavedSession(context);
  await page.goto("/");
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByLabel("Email address")).toBeVisible();
  await expect(page.getByRole("link", { name: "Forgot your password?" })).toHaveAttribute("href", "/forgot-password");
  await page.getByLabel("Email address").fill("another@example.test");
  await page.locator("#login-password").fill("SyntheticOtherPassword9!");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Verify your identity" })).toBeVisible();
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await expect(page.getByLabel("Email address")).toBeVisible();
  expect(fixture.counts()).toMatchObject({ loginRequests: 1, mfaRequests: 0 });
});

test("password-change notice is retained after saved-session rejection", async ({ context, page }) => {
  const fixture = authFixture();
  await fixture.install(context);
  await page.goto("/login?reason=password_changed");
  await expect(page.getByRole("status")).toHaveText(/Password changed/);
  await expect(page.getByLabel("Email address")).toBeVisible();
});
