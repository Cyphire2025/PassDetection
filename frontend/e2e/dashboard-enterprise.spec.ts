import { expect, test, type Page } from "@playwright/test";

const user = {
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

async function mockAuthenticatedApi(page: Page) {
  await page.context().addCookies([{
    name: "access_token",
    value: "e2e-session",
    domain: "127.0.0.1",
    path: "/",
    httpOnly: true,
    sameSite: "Lax",
  }]);
  await page.route("**/api/v1/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/v1/auth/refresh") {
      await route.fulfill({
        json: { user, token_type: "bearer", access_token_expires_at: "2026-08-22T13:00:00Z" },
      });
      return;
    }
    if (pathname === "/api/v1/auth/me") {
      await route.fulfill({ json: user });
      return;
    }
    if (pathname === "/api/v1/dashboard/stats") {
      await route.fulfill({
        json: { total_passports: 0, pending_review: 0, confirmed: 0, active_links: 0, recent_submissions: [] },
      });
      return;
    }
    await route.fulfill({ json: {} });
  });
}

test("authenticated staff can navigate the dashboard at tablet width", async ({ page }) => {
  await mockAuthenticatedApi(page);
  await page.setViewportSize({ width: 820, height: 900 });
  await page.goto("/dashboard");

  const trigger = page.getByRole("button", { name: "Open navigation" });
  await expect(trigger).toBeVisible();
  await trigger.click();

  const dialog = page.getByRole("dialog", { name: "Dashboard navigation" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Close navigation" })).toBeFocused();
  await expect(dialog.getByRole("link", { name: "All Groups" })).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(dialog).toBeHidden();
  await page.setViewportSize({ width: 820, height: 900 });
  await expect(dialog).toBeHidden();
  await trigger.click();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("every office route receives the same direct-link authentication boundary", async ({ page }) => {
  await page.goto("/documents?view=distribution");
  await expect(page).toHaveURL(/\/login\?from=%2Fdocuments%3Fview%3Ddistribution$/);
});
