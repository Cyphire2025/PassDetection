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
  const state = { drafts: [] as NotificationDraft[], batches: [] as NotificationBatch[], sendRequests: [] as string[], deleted: [] as string[], lookupDraftIds: [] as (string | null)[], patches: 0, previews: 0, loseNextSendResponse: false, dropNextSendBeforeRecord: false, unexpected: [] as string[] };
  await page.context().addCookies([{ name: "access_token", value: "synthetic-notification-session", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === "127.0.0.1" || url.hostname === "localhost") return route.continue();
    state.unexpected.push(`Blocked external request to ${url.origin}`);
    return route.abort("blockedbyclient");
  });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname; const method = request.method();
    if (new URL(request.url()).hostname !== "127.0.0.1") {
      state.unexpected.push(`Blocked non-local API request ${path}`);
      return route.abort("blockedbyclient");
    }
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
      const draftId = new URL(request.url()).searchParams.get("draft_id");
      state.lookupDraftIds.push(draftId);
      if (batch) return json(route, batch);
      if (draftId && state.deleted.includes(draftId)) return json(route, { detail: "notification_deleted_without_send" }, 410);
      return json(route, { detail: "Notification batch not found" }, 404);
    }
    if (path.startsWith(`${API}/batches/`)) return json(route, state.batches.find((item) => item.id === path.split("/").at(-1)));
    const match = path.match(new RegExp(`^${API}/([^/]+)(?:/(preview|send))?$`));
    const draft = state.drafts.find((item) => item.id === match?.[1]);
    if (match && draft) {
      if (method === "GET") return json(route, draft);
      if (method === "DELETE" && !match[2]) {
        if (new URL(request.url()).searchParams.get("expected_revision") !== String(draft.revision)) return json(route, { detail: "draft_conflict" }, 409);
        state.deleted.push(draft.id);
        state.drafts = state.drafts.filter((item) => item.id !== draft.id);
        return route.fulfill({ status: 204 });
      }
      const body = request.postDataJSON() as Record<string, unknown>;
      if (body.expected_revision !== draft.revision) return json(route, { detail: "draft_conflict" }, 409);
      if (method === "PATCH" && !match[2]) {
        const input = body as unknown as NotificationDraftInput;
        Object.assign(draft, {
          title: input.title, body: input.body, audience: input.audience,
          group_ids: [...input.group_ids], group_names: input.group_ids.map((id) => GROUP_NAMES[GROUP_IDS.indexOf(id)]!),
          revision: draft.revision + 1, status: "draft", updated_at: new Date().toISOString(),
        });
        state.patches += 1;
        return json(route, draft);
      }
      if (match[2] === "preview") {
        state.previews += 1;
        const ids = draft.audience === "all_active_trips" ? GROUP_IDS : draft.group_ids;
        return json(route, { draft_revision: draft.revision, preview_token: `review-${state.previews}`, expires_at: new Date(Date.now() + 600_000).toISOString(), group_count: ids.length, group_ids: ids, group_names: ids.map((id) => GROUP_NAMES[GROUP_IDS.indexOf(id)]), recipient_count: 12, role_counts: { passengers: 10, client_managers: 1, coordinators: 1 }, eligible_device_count: 8, no_active_registration_count: 4, provider_enabled: true, android_provider_enabled: true, ios_provider_enabled: false, delivery_window_hours: 24 });
      }
      if (match[2] === "send") {
        const requestId = String(body.request_id); state.sendRequests.push(requestId);
        if (state.dropNextSendBeforeRecord) { state.dropNextSendBeforeRecord = false; return route.abort("failed"); }
        let batch = state.batches.find((item) => item.request_id === requestId);
        if (!batch) {
          const ids = [...(draft.audience === "all_active_trips" ? GROUP_IDS : draft.group_ids)];
          batch = { id: `50000000-0000-4000-8000-${String(state.batches.length + 1).padStart(12, "0")}`, notification_id: draft.id, request_id: requestId, draft_revision: draft.revision, title: draft.title, body: draft.body, audience: draft.audience, group_ids: ids, group_names: ids.map((id) => GROUP_NAMES[GROUP_IDS.indexOf(id)]!), role_counts: { passengers: 10, client_managers: 1, coordinators: 1 }, created_at: new Date().toISOString(), expires_at: new Date(Date.now() + 86_400_000).toISOString(), provider_enabled: true,
            recipient_counts: { total: 12, queued: 10, sent: 1, failed: 0, cancelled: 0, unknown: 1, read: 0, no_active_registration: 4 },
            device_delivery_counts: { total: 8, submitting: 2, retry: 0, receipt_pending: 0, provider_accepted: 1, delivered: 0, failed: 0, cancelled: 0, unknown: 1 },
          }; state.batches.unshift(structuredClone(batch));
          draft.status = "sent";
          draft.last_sent_at = batch.created_at;
          draft.updated_at = batch.created_at;
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
    test("saved messages, reviewed resends, lost responses and permanent send history", async ({ page }, testInfo) => {
      test.setTimeout(120_000);
      const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
      const state = await mockNotifications(page);
      const screenshot = (name: string) => page.screenshot({ path: testInfo.outputPath(`${viewport.name}-notification-${name}.png`), fullPage: true });
      const originalTitle = "Lobby meeting updated";
      const originalBody = "Meet in the lobby at 8:30 AM.";
      const resendTitle = "Lobby time update";
      const resendBody = "Meet in the lobby at 8:45 AM instead.";

      await page.goto("/gc-app/notifications");
      await expect(page.getByRole("heading", { name: "Notifications", exact: true })).toBeVisible();
      await expect(page.getByRole("navigation", { name: "GC App", exact: true }).getByRole("link", { name: /Notifications/ })).toHaveAttribute("aria-current", "page");
      await expect(page.getByRole("heading", { name: "Your next update starts here" })).toBeVisible();
      await expect(page.getByRole("textbox", { name: "Notification title", exact: true })).not.toBeVisible();
      await screenshot("main");

      await page.getByRole("button", { name: "New notification", exact: true }).click();
      let editor = page.getByRole("dialog", { name: "New notification", exact: true });
      await editor.getByRole("textbox", { name: "Notification title", exact: true }).fill("Lobby meeting");
      await editor.getByLabel("Notification message", { exact: true }).fill("Meet in the lobby at 8 AM.");
      await editor.getByRole("checkbox", { name: /Synthetic Hill Trip/ }).check();
      await editor.getByRole("checkbox", { name: /Synthetic Beach Trip/ }).check();
      await expect(editor.getByText(/2 selected/)).toBeVisible();
      await editor.getByRole("button", { name: "Cancel", exact: true }).click();
      const discard = page.getByRole("dialog", { name: "Discard unsaved changes?" });
      await expect(discard).toBeVisible();
      await discard.getByRole("button", { name: "Keep editing" }).click();
      await expect(editor.getByRole("textbox", { name: "Notification title", exact: true })).toHaveValue("Lobby meeting");
      expect(state.drafts).toHaveLength(0);
      await screenshot("create");
      await editor.getByRole("button", { name: "Save notification", exact: true }).click();
      await expect(editor).not.toBeVisible();
      let saved = page.getByRole("article", { name: "Lobby meeting", exact: true });
      await expect(saved.getByText("Draft", { exact: true })).toBeVisible();
      expect(state.sendRequests).toHaveLength(0);
      expect(state.drafts).toHaveLength(1);

      await saved.getByRole("button", { name: "Edit", exact: true }).click();
      editor = page.getByRole("dialog", { name: "Edit notification", exact: true });
      await editor.getByRole("textbox", { name: "Notification title", exact: true }).fill(originalTitle);
      await editor.getByLabel("Notification message", { exact: true }).fill(originalBody);
      await editor.getByRole("button", { name: "Save notification", exact: true }).click();
      await expect(editor).not.toBeVisible();
      saved = page.getByRole("article", { name: originalTitle, exact: true });
      await expect(saved.getByText(originalBody, { exact: true })).toBeVisible();
      expect(state.patches).toBe(1);
      expect(state.sendRequests).toHaveLength(0);
      await saved.getByRole("button", { name: "Review & send", exact: true }).click();
      editor = page.getByRole("dialog", { name: "Edit notification", exact: true });
      await editor.getByRole("button", { name: "Review audience", exact: true }).click();
      let review = page.getByRole("dialog", { name: "Review phone notification", exact: true });
      await expect(review.getByText("Eligible recipients", { exact: true })).toBeVisible();
      expect(state.batches).toHaveLength(0);
      expect(state.drafts[0]?.group_ids).toEqual(GROUP_IDS);
      await screenshot("review");
      await review.getByRole("button", { name: "Send notification", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Delivery summary", exact: true })).toBeVisible();
      await expect(saved.getByText("Previously sent", { exact: true })).toBeVisible();
      expect(state.batches).toHaveLength(1);
      expect(state.batches[0]?.title).toBe(originalTitle);
      await screenshot("saved");

      const previousPreviewCount = state.previews;
      await saved.getByRole("button", { name: "Resend", exact: true }).click();
      editor = page.getByRole("dialog", { name: "Resend notification", exact: true });
      await expect(editor.getByRole("textbox", { name: "Notification title", exact: true })).toHaveValue(originalTitle);
      expect(state.sendRequests).toHaveLength(1);
      expect(state.previews).toBe(previousPreviewCount);
      await editor.getByRole("radio", { name: /All active GC App trips/ }).check();
      await expect(editor.getByLabel("Find active trips")).not.toBeVisible();
      await editor.getByRole("textbox", { name: "Notification title", exact: true }).fill(resendTitle);
      await editor.getByLabel("Notification message", { exact: true }).fill(resendBody);
      await editor.getByRole("button", { name: "Review audience", exact: true }).click();
      review = page.getByRole("dialog", { name: "Review phone notification", exact: true });
      await expect(review.getByText(/new deliberate send/)).toBeVisible();
      expect(state.batches[0]?.title).toBe(originalTitle);
      expect(state.batches[0]?.body).toBe(originalBody);
      expect(state.batches[0]?.audience).toBe("selected_groups");
      state.loseNextSendResponse = true;
      await review.getByRole("button", { name: "Send again", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Check the previous send", exact: true })).toBeVisible();
      expect(state.batches).toHaveLength(2);
      expect(state.sendRequests[0]).not.toEqual(state.sendRequests[1]);
      await page.reload();
      await expect(page.getByRole("button", { name: "New notification", exact: true })).toBeDisabled();
      await page.getByRole("button", { name: "Check recorded outcome", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Delivery summary", exact: true })).toBeVisible();
      await expect(page.getByText(/Unknown outcomes are not automatically resent/)).toBeVisible();
      expect(state.sendRequests).toHaveLength(2);
      expect(state.batches).toHaveLength(2);
      expect(state.batches[0]?.audience).toBe("all_active_trips");
      expect(state.patches).toBe(2);

      await page.getByRole("link", { name: "History", exact: true }).click();
      await expect(page).toHaveURL(/\/gc-app\/notifications\/history$/);
      await expect(page.getByRole("heading", { name: "Notification history", exact: true })).toBeVisible();
      const logs = () => viewport.name === "desktop" ? page.getByRole("table", { name: "Notification sends and provider status" }) : page.getByRole("article", { name: `Sent notification: ${originalTitle}` });
      await expect(logs().getByText(originalTitle, { exact: true })).toBeVisible();
      await expect(logs().getByText(originalBody, { exact: true })).toBeVisible();
      await expect(page.getByText("Page 1 · 2 records on this page")).toBeVisible();
      await expect(page.getByRole("button", { name: /Resend|Delete/ })).not.toBeVisible();
      await screenshot("history");
      const detailButton = viewport.name === "desktop"
        ? page.getByRole("button", { name: `View delivery details for ${originalTitle}` })
        : logs().getByRole("button", { name: "View delivery details", exact: true });
      await detailButton.click();
      const details = page.getByRole("dialog", { name: "Notification delivery details" });
      await expect(details.getByText("Provider accepted; phone display unconfirmed", { exact: true })).toBeVisible();
      await details.getByRole("button", { name: "Close Notification delivery details" }).click();
      await page.getByRole("link", { name: "Back to notifications", exact: true }).click();
      saved = page.getByRole("article", { name: resendTitle, exact: true });
      await saved.getByRole("button", { name: "Delete", exact: true }).click();
      const deletion = page.getByRole("dialog", { name: "Delete saved notification?" });
      await expect(deletion.getByText(/Its send history will stay in History/)).toBeVisible();
      await deletion.getByRole("button", { name: "Keep notification", exact: true }).click();
      expect(state.deleted).toHaveLength(0);
      await saved.getByRole("button", { name: "Delete", exact: true }).click();
      await deletion.getByRole("button", { name: "Delete notification", exact: true }).click();
      await expect(saved).not.toBeVisible();
      await expect(page.getByRole("heading", { name: "Your next update starts here" })).toBeVisible();
      expect(state.deleted).toHaveLength(1);
      expect(state.drafts).toHaveLength(0);
      expect(state.batches).toHaveLength(2);
      await page.getByRole("link", { name: "History", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Notification history", exact: true })).toBeVisible();
      await expect(page.getByText("Page 1 · 2 records on this page")).toBeVisible();
      await expect(logs().getByText(originalBody, { exact: true })).toBeVisible();
      await screenshot("history-after-delete");
      expect(state.unexpected).toEqual([]);
      expect(errors).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
    });

    for (const recoveryAction of ["Check recorded outcome", "Review and retry same request"]) {
      test(`deleted unsent draft safely releases recovery through ${recoveryAction}`, async ({ page }) => {
        const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
        const state = await mockNotifications(page);
        const storageKey = `gc-app:pending-notification:${AGENCY}:${USER.id}`;
        await page.goto("/gc-app/notifications");
        await page.getByRole("button", { name: "New notification", exact: true }).click();
        const editor = page.getByRole("dialog", { name: "New notification", exact: true });
        await editor.getByRole("textbox", { name: "Notification title", exact: true }).fill("Unsent test message");
        await editor.getByLabel("Notification message", { exact: true }).fill("This request never reached a recorded send.");
        await editor.getByRole("radio", { name: /All active GC App trips/ }).check();
        await editor.getByRole("button", { name: "Review audience", exact: true }).click();
        state.dropNextSendBeforeRecord = true;
        await page.getByRole("dialog", { name: "Review phone notification", exact: true }).getByRole("button", { name: "Send notification", exact: true }).click();
        const recovery = page.getByRole("heading", { name: "Check the previous send", exact: true });
        await expect(recovery).toBeVisible();
        expect(state.batches).toHaveLength(0);
        expect(state.sendRequests).toHaveLength(1);
        const draftId = state.drafts[0]!.id;

        // An ordinary not-found response cannot prove that the original request failed.
        await page.getByRole("button", { name: "Check recorded outcome", exact: true }).click();
        await expect(page.getByText(/No recorded send was found yet/)).toBeVisible();
        await expect(recovery).toBeVisible();
        await expect(page.getByRole("button", { name: "New notification", exact: true })).toBeDisabled();
        expect(await page.evaluate((key) => window.sessionStorage.getItem(key), storageKey)).not.toBeNull();
        await page.reload();
        await expect(recovery).toBeVisible();

        // Another authorized staff member deletes the saved draft while this tab is recovering.
        state.deleted.push(draftId);
        state.drafts = [];
        await page.getByRole("button", { name: recoveryAction, exact: true }).click();
        await expect(recovery).not.toBeVisible();
        await expect(page.getByRole("button", { name: "New notification", exact: true })).toBeEnabled();
        expect(await page.evaluate((key) => window.sessionStorage.getItem(key), storageKey)).toBeNull();
        expect(state.lookupDraftIds).toEqual([draftId, draftId]);
        expect(state.previews).toBe(1);
        expect(state.sendRequests).toHaveLength(1);
        expect(state.batches).toHaveLength(0);
        await page.getByRole("button", { name: "New notification", exact: true }).click();
        await expect(page.getByRole("dialog", { name: "New notification", exact: true }).getByRole("textbox", { name: "Notification title", exact: true })).toHaveValue("");
        expect(state.unexpected).toEqual([]);
        expect(errors).toEqual([]);
      });
    }
  });
}
