import { expect, test, type Page, type Route } from "@playwright/test";

const adminUser = {
  id: "e2e-admin",
  email: "admin@example.test",
  full_name: "E2E Agency Admin",
  role: "agency_admin",
  agency_id: "agency-e2e",
  is_active: true,
  last_login_at: null,
  created_at: "2026-08-22T00:00:00Z",
  updated_at: "2026-08-22T00:00:00Z",
  capabilities: [],
};

const session = {
  status: "authenticated",
  user: adminUser,
  token_type: "bearer",
  access_token_expires_at: "2099-08-22T13:00:00Z",
};

async function fulfillJson(route: Route, body: unknown, status = 200, headers = {}) {
  await route.fulfill({
    status,
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

async function installApiSession(
  page: Page,
  options: {
    user?: typeof adminUser;
    refreshStatus?: number;
    onLogout?: () => void;
  } = {},
) {
  const user = options.user ?? adminUser;
  await page.context().addCookies([{
    name: "access_token",
    value: "e2e-session",
    domain: "127.0.0.1",
    path: "/",
    httpOnly: true,
    sameSite: "Lax",
  }]);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;

    if (pathname === "/api/v1/auth/refresh") {
      if (options.refreshStatus && options.refreshStatus !== 200) {
        await fulfillJson(route, {
          error: { code: "AUTH_REFRESH_REJECTED", message: "The session is no longer valid." },
        }, options.refreshStatus, {
          "set-cookie": "access_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax",
        });
        return;
      }
      await fulfillJson(route, { ...session, user });
      return;
    }
    if (pathname === "/api/v1/auth/me") {
      await fulfillJson(route, user);
      return;
    }
    if (pathname === "/api/v1/auth/logout") {
      options.onLogout?.();
      await fulfillJson(route, { message: "Signed out" }, 200, {
        "set-cookie": "access_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax",
      });
      return;
    }
    if (pathname === "/api/v1/notifications/feed") {
      await fulfillJson(route, { items: [], unread_count: 0, next_cursor: null });
      return;
    }
    if (pathname === "/api/v1/dashboard/stats") {
      await fulfillJson(route, {
        total_passports: 0,
        pending_review: 0,
        confirmed: 0,
        active_links: 0,
        recent_submissions: [],
      });
      return;
    }
    await fulfillJson(route, request.method() === "GET" ? [] : {});
  });
}

test("credential login restores a cookie session and logout clears browser-owned state", async ({ page }) => {
  let logoutCalled = false;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/v1/auth/login") {
      await fulfillJson(route, session, 200, {
        "set-cookie": "access_token=e2e-session; Path=/; HttpOnly; SameSite=Lax",
      });
      return;
    }
    if (pathname === "/api/v1/auth/refresh") {
      await fulfillJson(route, session);
      return;
    }
    if (pathname === "/api/v1/auth/me") {
      await fulfillJson(route, adminUser);
      return;
    }
    if (pathname === "/api/v1/auth/logout") {
      logoutCalled = true;
      await fulfillJson(route, { message: "Signed out" }, 200, {
        "set-cookie": "access_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax",
      });
      return;
    }
    if (pathname === "/api/v1/notifications/feed") {
      await fulfillJson(route, { items: [], unread_count: 0, next_cursor: null });
      return;
    }
    if (pathname === "/api/v1/dashboard/stats") {
      await fulfillJson(route, {
        total_passports: 0,
        pending_review: 0,
        confirmed: 0,
        active_links: 0,
        recent_submissions: [],
      });
      return;
    }
    await fulfillJson(route, request.method() === "GET" ? [] : {});
  });

  await page.goto("/login?from=%2Fdashboard");
  await page.getByLabel("Email address").fill("admin@example.test");
  await page.locator("#login-password").fill("CorrectHorseBattery9");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await page.evaluate(() => localStorage.setItem("passdetection:e2e-sensitive", "must-clear"));
  await page.getByRole("button", { name: "Sign out" }).click();

  await expect(page).toHaveURL(/\/login(?:\?.*)?$/);
  await expect.poll(() => logoutCalled).toBe(true);
  await expect.poll(() => page.evaluate(() => localStorage.getItem("passdetection:e2e-sensitive"))).toBeNull();
});

test("a rejected refresh expires the local session and explains the redirect", async ({ page }) => {
  await installApiSession(page, { refreshStatus: 401 });
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login\?reason=session_expired&from=%2Fdashboard$/);
});

test("a lower-privilege direct-link journey is denied and returned to its safe workspace", async ({ page }) => {
  await installApiSession(page, {
    user: { ...adminUser, id: "e2e-staff", email: "staff@example.test", role: "agency_staff" },
  });

  await page.goto("/gc-app/client-manager-accounts");
  await expect(page).toHaveURL(/\/passports$/);
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
});
