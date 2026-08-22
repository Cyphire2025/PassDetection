import { expect, test, type Page, type Route } from "@playwright/test";

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

async function json(route: Route, body: unknown) {
  await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
}

async function mockOfficeApi(page: Page) {
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
      await json(route, {
        status: "authenticated",
        user,
        token_type: "bearer",
        access_token_expires_at: "2099-08-22T13:00:00Z",
      });
      return;
    }
    if (pathname === "/api/v1/auth/me") {
      await json(route, user);
      return;
    }
    if (pathname === "/api/v1/notifications/feed") {
      await json(route, { items: [], unread_count: 0, next_cursor: null });
      return;
    }
    if (pathname === "/api/v1/email-integrations/inbox") {
      await json(route, {
        items: [],
        next_cursor: null,
        counts: {
          needs_attention: 0,
          upcoming_deadlines: 0,
          drafts_ready: 0,
          waiting: 0,
          completed_automatically: 0,
          all_activity: 0,
        },
      });
      return;
    }
    if (request.method() === "GET") {
      await json(route, []);
      return;
    }
    await json(route, {});
  });
}

test("critical office workspaces render and retain their primary keyboard-operable controls", async ({ page }) => {
  await mockOfficeApi(page);

  await page.goto("/passports");
  await expect(page.getByRole("heading", { name: "All Groups", level: 1 })).toBeVisible();
  const passportFilter = page.getByRole("searchbox", { name: "Filter groups by destination" });
  await passportFilter.fill("Singapore");
  await expect(passportFilter).toHaveValue("Singapore");

  await page.goto("/documents");
  await expect(page.getByRole("heading", { name: "Documents", level: 1 })).toBeVisible();
  await page.getByRole("link", { name: /Open distribution control/i }).click();
  await expect(page).toHaveURL(/\/documents\/distribution$/);

  await page.goto("/rooming");
  await expect(page.getByRole("heading", { name: "Rooming Lists", level: 1 })).toBeVisible();
  const roomingSearch = page.getByRole("searchbox", { name: "Search rooming groups" });
  await roomingSearch.fill("Bangkok");
  await expect(roomingSearch).toHaveValue("Bangkok");

  await page.goto("/tour-operations/group-assignments");
  await expect(page.getByRole("heading", { name: "Tour Ops", level: 1 })).toBeVisible();
  const coverageFilter = page.getByRole("button", { name: "Needs coverage (0)" });
  await coverageFilter.click();
  await expect(coverageFilter).toHaveAttribute("aria-pressed", "true");

  await page.goto("/whatsapp");
  await expect(page.getByRole("heading", { name: "WhatsApp", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Create Broadcast" }).first().click();
  await expect(page.getByRole("heading", { name: "Create WhatsApp Broadcast Group" })).toBeVisible();

  await page.goto("/email-integrations/inbox");
  await expect(page.getByRole("heading", { name: "Operations Inbox", level: 1 })).toBeVisible();
  const deadlines = page.getByRole("button", { name: /Deadlines Upcoming and overdue/ });
  await deadlines.click();
  await expect(deadlines).toHaveAttribute("aria-pressed", "true");
});
