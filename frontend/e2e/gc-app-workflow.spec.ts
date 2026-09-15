import { expect, test, type Page, type Route } from "@playwright/test";

const ROOT = "/api/v1/gc-app/admin";
const GROUP_ID = "gc-trip-paused";
const NEW_GROUP_ID = "gc-trip-new";
const COMPANY = { id: "gc-company", name: "Example Travel Client", status: "active" };
const user = {
  id: "gc-e2e-admin", email: "staff@example.test", full_name: "GC Workflow Staff",
  role: "agency_admin", agency_id: "gc-agency", is_active: true,
  last_login_at: null, created_at: "2026-09-15T00:00:00Z", updated_at: "2026-09-15T00:00:00Z",
  capabilities: ["gc_app.manage"],
};

function control(id = GROUP_ID) {
  return {
    group_id: id, name: id === GROUP_ID ? "Singapore staff trip" : "Closed collection trip",
    destination: "Singapore", travel_date: "2030-11-01", return_date: "2030-11-07", lifecycle_status: "closed",
    client_organization_id: COMPANY.id, client_organization_name: COMPANY.name,
    enabled: false, passenger_access_enabled: false, client_manager_access_enabled: true, coordinator_access_enabled: true,
    my_photos_enabled: false, access_starts_at: null as string | null, access_expires_at: "2035-01-01T12:00:00Z" as string | null,
    revoked_at: "2026-09-15T12:00:00Z" as string | null, revision: 4,
    itinerary_version: 1, common_document_version: 2, announcement_version: 0,
    last_successful_sync_at: "2026-09-15T10:00:00Z", active_mobile_users: 0, synced_device_count: 2,
    app_availability: "paused", app_availability_reason: "app_disabled" as string | null,
    app_availability_evaluated_at: new Date().toISOString(),
  };
}

interface RawAnnouncement {
  id: string; title: string; message: string; priority: string; status: string; version: number;
  available_from: string | null; available_until: string | null; updated_at: string;
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockGcApp(page: Page) {
  const state = {
    control: control(), added: null as ReturnType<typeof control> | null,
    announcements: [] as RawAnnouncement[], writes: [] as { method: string; path: string; body: Record<string, unknown> }[],
    audit: [] as { id: string; action: string; actor_email: string; created_at: string }[], unexpected: [] as string[],
  };
  const record = (action: string) => state.audit.unshift({
    id: `event-${state.audit.length + 1}`, action, actor_email: user.email, created_at: new Date().toISOString(),
  });
  const groupRow = (access: ReturnType<typeof control>) => ({
    id: access.group_id, name: access.name, destination: access.destination, travel_date: access.travel_date,
    return_date: access.return_date, lifecycle_status: access.lifecycle_status,
    gc_enabled: access.enabled, client_organization_id: COMPANY.id, client_organization_name: COMPANY.name,
    access, app_availability: access.app_availability, app_availability_reason: access.app_availability_reason,
    app_availability_evaluated_at: access.app_availability_evaluated_at,
  });
  await page.context().addCookies([{
    name: "access_token", value: "synthetic-gc-workflow", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax",
  }]);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    if (path === "/api/v1/auth/refresh") return json(route, {
      status: "authenticated", user, token_type: "bearer", access_token_expires_at: new Date(Date.now() + 30 * 60_000).toISOString(),
    });
    if (path === "/api/v1/auth/me") return json(route, user);
    if (path === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (!path.startsWith(ROOT)) return json(route, method === "GET" ? [] : {});
    const body = method === "GET" ? {} : request.postDataJSON() as Record<string, unknown>;
    if (method !== "GET") state.writes.push({ method, path, body });
    if (path === `${ROOT}/client-organizations/search`) return json(route, { items: [COMPANY], total: 1, offset: 0, limit: 20 });
    if (path === `${ROOT}/groups` && method === "GET") {
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 20);
      const items = url.searchParams.get("unconfigured_only") === "true"
        ? state.added ? [] : [{ ...groupRow(control(NEW_GROUP_ID)), access: null, gc_enabled: false }]
        : [groupRow(state.control), ...(state.added ? [groupRow(state.added)] : [])]
          .filter((item) => !url.searchParams.get("availability") || item.app_availability === url.searchParams.get("availability"));
      return json(route, { items: items.slice(offset, offset + limit), total: items.length, offset, limit });
    }
    if (path === `${ROOT}/groups/${NEW_GROUP_ID}` && method === "PUT") {
      state.added = { ...control(NEW_GROUP_ID), ...body, enabled: true, revoked_at: null, revision: 1,
        app_availability: "active", app_availability_reason: null };
      record("gc_app.group_added");
      return json(route, state.added);
    }
    if (path === `${ROOT}/groups/${GROUP_ID}` && method === "GET") return json(route, state.control);
    if (path === `${ROOT}/groups/${GROUP_ID}` && method === "PUT") {
      if (body.expected_revision !== state.control.revision) return json(route, { message: "Stale synthetic revision" }, 409);
      state.control = { ...state.control, ...body, revision: state.control.revision + 1,
        revoked_at: body.enabled ? null : new Date().toISOString(),
        app_availability: body.enabled ? "active" : "paused", app_availability_reason: body.enabled ? null : "app_disabled",
        app_availability_evaluated_at: new Date().toISOString() };
      record(body.enabled ? "gc_app.group_enabled" : "gc_app.group_disabled");
      return json(route, state.control);
    }
    if (path === `${ROOT}/groups/${GROUP_ID}/announcements/page`) {
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 25);
      return json(route, { items: state.announcements.slice(offset, offset + limit), total: state.announcements.length, offset, limit });
    }
    if (path === `${ROOT}/groups/${GROUP_ID}/announcements` && method === "GET") return json(route, state.announcements);
    if (path === `${ROOT}/groups/${GROUP_ID}/common-documents`) return json(route, []);
    if (path === `${ROOT}/groups/${GROUP_ID}/audit`) {
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 25);
      return json(route, { items: state.audit.slice(offset, offset + limit), total: state.audit.length, offset, limit });
    }
    const create = path === `${ROOT}/groups/${GROUP_ID}/announcements` && method === "POST";
    const edit = path.match(new RegExp(`^${ROOT}/groups/${GROUP_ID}/announcements/([^/]+)$`)) && method === "PUT";
    if (create || edit) {
      if (body.expected_access_revision !== state.control.revision) return json(route, { message: "Stale synthetic access revision" }, 409);
      const announcement: RawAnnouncement = {
        id: `announcement-${state.control.announcement_version + 1}`, title: String(body.title), message: String(body.message),
        priority: String(body.priority), status: body.publish ? "published" : "draft", version: state.control.announcement_version + 1,
        available_from: body.available_from as string | null, available_until: body.available_until as string | null,
        updated_at: new Date().toISOString(),
      };
      if (edit) state.announcements = state.announcements.filter((item) => !path.endsWith(`/${item.id}`));
      state.announcements.unshift(announcement);
      state.control.announcement_version += 1;
      state.control.revision += 1;
      record(body.publish ? "gc_app.announcement_published" : "gc_app.announcement_draft_saved");
      return json(route, announcement);
    }
    state.unexpected.push(`${method} ${path}`);
    return json(route, { message: "Unexpected synthetic GC API request" }, 404);
  });
  return state;
}

for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "phone", width: 390, height: 844 }]) {
  test.describe(viewport.name, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height }, isMobile: viewport.name === "phone" });
    test("closed groups and paused trips retain a clear, revision-safe publishing workflow", async ({ page }, testInfo) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      const state = await mockGcApp(page);
      await page.goto("/gc-app");
      await expect(page).toHaveURL(/\/gc-app\/app-controls$/);
      await expect(page.getByRole("heading", { name: "App Controls", exact: true })).toBeVisible();
      await expect(page.getByText("Singapore staff trip", { exact: true })).toBeVisible();
      await expect(page.getByText("Paused", { exact: true })).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-trip-list.png`), fullPage: true });

      await page.getByRole("button", { name: "Add group to GC App", exact: true }).click();
      const picker = page.getByRole("dialog", { name: "Add group to GC App" });
      await expect(picker.getByText("Closed collection trip", { exact: true })).toBeVisible();
      await picker.getByRole("combobox", { name: /Assigned company\/client/ }).click();
      await page.getByRole("option", { name: COMPANY.name, exact: true }).click();
      await picker.getByText("Closed collection trip", { exact: true }).locator("..").locator("..").getByRole("button", { name: "Add", exact: true }).click();
      await expect(picker).not.toBeVisible();
      expect(state.added?.lifecycle_status).toBe("closed");
      expect(state.added?.enabled).toBe(true);
      await page.locator(`a[href='/gc-app/app-controls/${GROUP_ID}']`).click();
      await expect(page.getByRole("tab", { name: "Overview", exact: true })).toHaveAttribute("aria-selected", "true");
      await expect(page.getByText("App: Paused", { exact: true })).toBeVisible();
      for (const name of ["Overview", "Access & features", "Documents", "Announcements", "History"]) {
        await expect(page.getByRole("tab", { name, exact: true })).toBeInViewport();
      }
      await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-overview.png`), fullPage: true });

      await page.getByRole("tab", { name: "Access & features", exact: true }).click();
      await expect(page.getByRole("switch", { name: "My Photos", exact: true })).toBeDisabled();
      await page.getByRole("button", { name: "Restore app access", exact: true }).click();
      await expect(page.getByText("App: Available now", { exact: true })).toBeVisible();
      expect(state.control.passenger_access_enabled).toBe(false);
      expect(state.control.access_expires_at).toBe("2035-01-01T12:00:00Z");
      await page.getByLabel("Access expires", { exact: true }).fill("2035-02-01T18:00");
      await page.getByRole("switch", { name: "Passenger access", exact: true }).click();
      await expect(page.getByRole("switch", { name: "Passenger access", exact: true })).toHaveAttribute("aria-checked", "true");
      await expect(page.getByLabel("Access expires", { exact: true })).toHaveValue("2035-02-01T18:00");
      await page.getByRole("tab", { name: "Overview", exact: true }).click();
      await page.getByRole("tab", { name: "Access & features", exact: true }).click();
      await expect(page.getByLabel("Access expires", { exact: true })).toHaveValue("2035-02-01T18:00");
      await page.getByRole("button", { name: "Save access window", exact: true }).click();
      await expect(page.getByText("App-access dates saved.", { exact: true })).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-access.png`), fullPage: true });

      await page.getByRole("tab", { name: "Announcements", exact: true }).click();
      await page.getByRole("textbox", { name: "Title", exact: true }).fill("Meet in the lobby");
      await page.getByRole("textbox", { name: "Message", exact: true }).fill("Please arrive at 8 AM.");
      await page.getByRole("button", { name: "Save draft", exact: true }).click();
      const item = page.getByRole("article", { name: "Meet in the lobby", exact: true });
      await expect(item.getByText("Draft", { exact: true })).toBeVisible();
      await item.getByRole("button", { name: "Edit", exact: true }).click();
      await page.getByRole("textbox", { name: "Message", exact: true }).fill("Please arrive at 8:15 AM.");
      const writesBeforePublish = state.writes.length;
      await page.getByRole("button", { name: "Save & publish", exact: true }).click();
      await expect(item.getByText("Published", { exact: true })).toBeVisible();
      expect(state.writes.slice(writesBeforePublish)).toEqual([expect.objectContaining({
        method: "PUT", path: `${ROOT}/groups/${GROUP_ID}/announcements/announcement-1`,
        body: expect.objectContaining({ publish: true, message: "Please arrive at 8:15 AM." }),
      })]);
      await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-announcements.png`), fullPage: true });
      await page.getByRole("tab", { name: "History", exact: true }).click();
      await expect(page.getByRole("tabpanel", { name: "History", exact: true }).getByText("gc app / announcement published", { exact: true })).toBeVisible();
      expect(state.control.lifecycle_status).toBe("closed");
      expect(state.unexpected).toEqual([]);
      expect(errors).toEqual([]);
      const horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
      expect(horizontalOverflow).toBe(false);
    });
  });
}
