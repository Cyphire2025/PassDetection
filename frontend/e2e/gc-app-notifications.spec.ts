import { expect, test, type Page, type Route } from "@playwright/test";
import type { NotificationBatch, NotificationDraft, NotificationDraftInput } from "../features/gc-app/notifications/notification-types";

const ROOT = "/api/v1/gc-app/admin";
const API = `${ROOT}/notifications`;
const AGENCY = "10000000-0000-4000-8000-000000000001";
const GROUP_IDS = ["30000000-0000-4000-8000-000000000001", "30000000-0000-4000-8000-000000000002"];
const GROUP_NAMES = ["Synthetic Hill Trip", "Synthetic Beach Trip"];
const USER = { id: "20000000-0000-4000-8000-000000000001", email: "notifications@example.test", full_name: "Notification Test Staff", role: "agency_admin", agency_id: AGENCY, is_active: true, last_login_at: null, created_at: "2026-09-15T00:00:00Z", updated_at: "2026-09-15T00:00:00Z", capabilities: ["gc_app.manage"] };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function mockNotifications(page: Page) {
  const state = { drafts: [] as NotificationDraft[], batches: [] as NotificationBatch[], sendRequests: [] as string[], previews: 0, loseNextSendResponse: false, unexpected: [] as string[] };
  await page.context().addCookies([{ name: "access_token", value: "synthetic-notification-session", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname; const method = request.method();
    if (path === "/api/v1/auth/refresh") return json(route, { status: "authenticated", user: USER, token_type: "bearer", access_token_expires_at: new Date(Date.now() + 1_800_000).toISOString() });
    if (path === "/api/v1/auth/me") return json(route, USER);
    if (path === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (!path.startsWith(ROOT)) return json(route, method === "GET" ? [] : {});
    if (path === `${ROOT}/groups`) return json(route, { items: GROUP_IDS.map((id, i) => ({ id, name: GROUP_NAMES[i], lifecycle_status: "closed", destination: i ? "Coast" : "Hills", travel_date: null, return_date: null, gc_enabled: true, client_organization_id: null, client_organization_name: null,
      access: { group_id: id, name: GROUP_NAMES[i], enabled: true, lifecycle_status: "closed", passenger_access_enabled: true, client_manager_access_enabled: true, coordinator_access_enabled: true, access_starts_at: null, access_expires_at: null, revoked_at: null, revision: 1, app_availability: "active", app_availability_reason: null, app_availability_evaluated_at: new Date().toISOString() },
    })), total: 2, offset: 0, limit: 20 });
    if (path === API && method === "GET") return json(route, { items: state.drafts, next_cursor: null });
    if (path === API && method === "POST") {
      const body = request.postDataJSON() as NotificationDraftInput;
      const draft: NotificationDraft = { ...body, id: `40000000-0000-4000-8000-${String(state.drafts.length + 1).padStart(12, "0")}`, revision: 1, status: "draft", group_names: body.group_ids.map((id) => GROUP_NAMES[GROUP_IDS.indexOf(id)]!), last_sent_at: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
      state.drafts.unshift(draft); return json(route, draft, 201);
    }
    if (path === `${API}/batches`) return json(route, { items: state.batches, next_cursor: null });
    if (path.startsWith(`${API}/batches/by-request/`)) {
      const batch = state.batches.find((item) => item.request_id === path.split("/").at(-1));
      return batch ? json(route, batch) : json(route, { detail: "Notification batch not found" }, 404);
    }
    if (path.startsWith(`${API}/batches/`)) return json(route, state.batches.find((item) => item.id === path.split("/").at(-1)));
    const match = path.match(new RegExp(`^${API}/([^/]+)(?:/(preview|send))?$`));
    const draft = state.drafts.find((item) => item.id === match?.[1]);
    if (match && draft) {
      if (method === "GET") return json(route, draft);
      const body = request.postDataJSON() as Record<string, unknown>;
      if (match[2] === "preview") {
        state.previews += 1;
        const ids = draft.audience === "all_active_trips" ? GROUP_IDS : draft.group_ids;
        return json(route, { draft_revision: draft.revision, preview_token: `review-${state.previews}`, expires_at: new Date(Date.now() + 600_000).toISOString(), group_count: ids.length, group_ids: ids, group_names: ids.map((id) => GROUP_NAMES[GROUP_IDS.indexOf(id)]), recipient_count: 12, role_counts: { passengers: 10, client_managers: 1, coordinators: 1 }, eligible_device_count: 8, no_active_registration_count: 4, provider_enabled: true, android_provider_enabled: true, ios_provider_enabled: false, delivery_window_hours: 24 });
      }
      if (match[2] === "send") {
        const requestId = String(body.request_id); state.sendRequests.push(requestId);
        let batch = state.batches.find((item) => item.request_id === requestId);
        if (!batch) {
          const ids = draft.audience === "all_active_trips" ? GROUP_IDS : draft.group_ids;
          batch = { id: `50000000-0000-4000-8000-${String(state.batches.length + 1).padStart(12, "0")}`, notification_id: draft.id, request_id: requestId, draft_revision: draft.revision, title: draft.title, body: draft.body, audience: draft.audience, group_ids: ids, group_names: ids.map((id) => GROUP_NAMES[GROUP_IDS.indexOf(id)]!), role_counts: { passengers: 10, client_managers: 1, coordinators: 1 }, created_at: new Date().toISOString(), expires_at: new Date(Date.now() + 86_400_000).toISOString(), provider_enabled: true,
            recipient_counts: { total: 12, queued: 10, sent: 1, failed: 0, cancelled: 0, unknown: 1, read: 0, no_active_registration: 4 },
            device_delivery_counts: { total: 8, submitting: 2, retry: 0, receipt_pending: 0, provider_accepted: 1, delivered: 0, failed: 0, cancelled: 0, unknown: 1 },
          }; state.batches.unshift(batch);
        }
        if (state.loseNextSendResponse) { state.loseNextSendResponse = false; return route.abort("failed"); }
        return json(route, batch, 202);
      }
    }
    state.unexpected.push(`${method} ${path}`); return json(route, { detail: "Unexpected synthetic request" }, 404);
  });
  return state;
}

for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "phone", width: 390, height: 844 }]) {
  test.describe(viewport.name, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height }, isMobile: viewport.name === "phone" });
    test("separate notifications review both audiences, deliberate resends and recover a lost response", async ({ page }, testInfo) => {
      const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
      const state = await mockNotifications(page);
      await page.goto("/gc-app/notifications");
      await expect(page.getByRole("heading", { name: "Notifications", exact: true })).toBeVisible();
      await expect(page.getByRole("navigation", { name: "GC App", exact: true }).getByRole("link", { name: /Notifications/ })).toHaveAttribute("aria-current", "page");
      await page.getByRole("textbox", { name: "Notification title", exact: true }).fill("Lobby meeting");
      await page.getByLabel(/Notification message/).fill("Meet in the lobby at 8 AM.");
      await page.getByRole("checkbox", { name: /Synthetic Hill Trip/ }).check();
      await page.getByRole("checkbox", { name: /Synthetic Beach Trip/ }).check();
      await expect(page.getByText(/2 selected/)).toBeVisible();
      await page.getByRole("radio", { name: /All active GC App trips/ }).check();
      await expect(page.getByLabel("Find active trips")).not.toBeVisible();
      await page.getByRole("radio", { name: /Specific groups/ }).check();
      await page.getByRole("checkbox", { name: /Synthetic Hill Trip/ }).check();
      await page.getByRole("checkbox", { name: /Synthetic Beach Trip/ }).check();
      await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-notification-composer.png`), fullPage: true });
      await page.getByRole("button", { name: "Review audience", exact: true }).click();
      let dialog = page.getByRole("dialog", { name: "Review phone notification", exact: true });
      await expect(dialog.getByText("Eligible recipients", { exact: true })).toBeVisible();
      expect(state.batches).toHaveLength(0);
      expect(state.drafts[0]?.group_ids).toEqual(GROUP_IDS);
      await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-notification-review.png`), fullPage: true });
      await dialog.getByRole("button", { name: "Send notification", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Delivery summary", exact: true })).toBeVisible();
      expect(state.batches).toHaveLength(1);
      await page.getByRole("button", { name: "Prepare resend", exact: true }).click();
      await expect(page.getByRole("textbox", { name: "Notification title", exact: true })).toHaveValue("Lobby meeting");
      expect(state.batches).toHaveLength(1);
      await page.getByRole("radio", { name: /All active GC App trips/ }).check();
      await page.getByRole("button", { name: "Review audience", exact: true }).click();
      dialog = page.getByRole("dialog", { name: "Review phone notification", exact: true });
      await expect(dialog.getByText(/new deliberate send/)).toBeVisible();
      state.loseNextSendResponse = true;
      await dialog.getByRole("button", { name: "Send again", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Check the previous send", exact: true })).toBeVisible();
      expect(state.batches).toHaveLength(2);
      expect(state.sendRequests[0]).not.toEqual(state.sendRequests[1]);
      await page.reload();
      await expect(page.getByRole("button", { name: "Review audience", exact: true })).toBeDisabled();
      await page.getByRole("button", { name: "Check recorded outcome", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Delivery summary", exact: true })).toBeVisible();
      await expect(page.getByText(/Unknown outcomes are not automatically resent/)).toBeVisible();
      expect(state.sendRequests).toHaveLength(2);
      expect(state.batches).toHaveLength(2);
      expect(state.batches[0]?.audience).toBe("all_active_trips");
      expect(state.unexpected).toEqual([]);
      expect(errors).toEqual([]);
      await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-notification-outcome.png`), fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
    });
  });
}
