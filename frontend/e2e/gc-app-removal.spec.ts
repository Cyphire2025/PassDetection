import { expect, test, type Page, type Route } from "@playwright/test";

const ROOT = "/api/v1/gc-app/admin";
const NAME = "Old archived Dubai trip";
const GROUP = "old-gc-trip";
const USER = {
  id: "removal-manager", email: "manager@example.test", full_name: "Removal Test Manager",
  role: "agency_manager", agency_id: "test-agency", is_active: true, capabilities: ["gc_app.manage"],
  last_login_at: null, created_at: "2026-09-16T00:00:00Z", updated_at: "2026-09-16T00:00:00Z",
};

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockRemoval(page: Page) {
  const access = {
    group_id: GROUP, name: NAME, destination: "Dubai", lifecycle_status: "archived",
    travel_date: null, return_date: null, client_organization_id: "company", client_organization_name: "Example Client",
    enabled: false, passenger_access_enabled: false, coordinator_access_enabled: false, client_manager_access_enabled: false,
    access_starts_at: null, access_expires_at: null, revoked_at: "2026-09-15T12:00:00Z", removed_at: null as string | null,
    revision: 7, itinerary_version: 1, common_document_version: 2, announcement_version: 1,
    active_mobile_users: 0, synced_device_count: 0, last_successful_sync_at: null,
    app_availability: "unavailable", app_availability_reason: "group_archived", app_availability_evaluated_at: new Date().toISOString(),
  };
  const state = { access, conflict: true, deletes: [] as number[], unexpected: [] as string[] };
  await page.context().addCookies([{
    name: "access_token", value: "synthetic-gc-removal", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax",
  }]);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    if (path === "/api/v1/auth/refresh") return json(route, {
      status: "authenticated", user: USER, token_type: "bearer", access_token_expires_at: new Date(Date.now() + 1800_000).toISOString(),
    });
    if (path === "/api/v1/auth/me") return json(route, USER);
    if (path === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (!path.startsWith(ROOT) && method === "GET") return json(route, []);
    if (path === `${ROOT}/groups` && method === "GET") {
      expect(url.searchParams.get("agency_id")).toBe(USER.agency_id);
      const items = state.access.removed_at ? [] : [{ id: GROUP, name: NAME, lifecycle_status: "archived",
        destination: "Dubai", gc_enabled: false, access: state.access }];
      return json(route, { items, total: items.length, offset: 0, limit: 20 });
    }
    if (path === `${ROOT}/groups/${GROUP}` && method === "GET") return json(route, state.access);
    if (path === `${ROOT}/groups/${GROUP}` && method === "DELETE") {
      expect(url.searchParams.get("agency_id")).toBe(USER.agency_id);
      state.deletes.push(Number(url.searchParams.get("expected_revision")));
      if (state.conflict) {
        state.conflict = false;
        state.access.revision++;
        return json(route, { detail: "GC App settings changed; refresh and retry" }, 409);
      }
      expect(state.deletes.at(-1)).toBe(state.access.revision);
      state.access.removed_at = new Date().toISOString();
      state.access.revision++;
      return route.fulfill({ status: 204 });
    }
    if (path === `${ROOT}/groups/${GROUP}/audit` && method === "GET") return json(route, {
      items: [{ id: "retained-event", action: "gc_app.group_removed", actor_email: USER.email, created_at: new Date().toISOString() }],
      total: 1, offset: 0, limit: 25,
    });
    state.unexpected.push(`${method} ${path}`);
    return json(route, { detail: "Unexpected synthetic API request" }, 404);
  });
  return state;
}

for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "phone", width: 390, height: 844 }]) {
  test.describe(viewport.name, () => {
    test.use({ viewport, isMobile: viewport.name === "phone" });
    test("manually removes an old GC App entry after a fresh revision review and preserves its history", async ({ page }, testInfo) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      const state = await mockRemoval(page);
      await page.goto("/gc-app/app-controls");
      await expect(page.getByRole("heading", { name: NAME })).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-remove-action.png`), fullPage: true });
      await page.getByRole("button", { name: "Remove from GC App", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Remove group from GC App?" });
      await expect(dialog.getByRole("button", { name: "Remove from GC App" })).toBeDisabled();
      await expect(dialog).toContainText("The original passport group, travellers, documents and history will be kept.");
      await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
      expect(state.deletes).toEqual([]);
      await page.getByRole("button", { name: "Remove from GC App", exact: true }).click();
      await dialog.getByRole("textbox").fill(NAME);
      await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-remove-confirmation.png`), fullPage: true });
      await dialog.getByRole("button", { name: "Remove from GC App", exact: true }).click();
      await expect(dialog.getByRole("alert")).toContainText("GC App settings changed; refresh and retry");
      expect(state.deletes).toEqual([7]);
      await dialog.getByRole("button", { name: "Reload trip details" }).click();
      await expect(dialog.getByRole("textbox")).toHaveValue("");
      await dialog.getByRole("textbox").fill(NAME);
      await dialog.getByRole("button", { name: "Remove from GC App", exact: true }).click();
      await expect(dialog).not.toBeVisible();
      await expect(page.getByText("No GC App trips found", { exact: true })).toBeVisible();
      expect(state.deletes).toEqual([7, 8]);
      await page.reload();
      await expect(page.getByText("No GC App trips found", { exact: true })).toBeVisible();
      await page.goto(`/gc-app/app-controls/${GROUP}`);
      await expect(page.getByText("Removed from GC App", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "View history" }).click();
      await expect(page.getByText("gc app / group removed", { exact: true })).toBeVisible();
      await expect(page.getByRole("tab", { name: "Access & features" })).toHaveCount(0);
      expect(state.access.lifecycle_status).toBe("archived");
      expect(state.unexpected).toEqual([]);
      expect(errors).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
    });
  });
}
