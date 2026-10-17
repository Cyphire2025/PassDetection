import { expect, test, type Page, type Route } from "@playwright/test";
import { catalog } from "./support/whatsapp-workspace-fixture";
import type { WhatsAppBroadcastGroupDetail } from "../features/whatsapp/api/whatsapp.api";

const staff = {
  id: "archive-test-staff", email: "archive@example.test", full_name: "Archive Test Staff",
  role: "agency_staff", agency_id: "archive-test-agency", is_active: true,
  last_login_at: null, created_at: "2026-09-19T00:00:00Z", updated_at: "2026-09-19T00:00:00Z", capabilities: [],
};

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockBroadcastApi(page: Page) {
  let group: WhatsAppBroadcastGroupDetail = {
    id: "broadcast-a", name: "September travellers", is_archived: false, archived_at: null,
    created_at: "2026-09-18T09:00:00Z", updated_at: "2026-09-19T09:00:00Z",
    recipient_count: 1, total_contact_count: 1, recipient_opt_in_confirmed: true,
    recipients: [{
      id: "recipient-a", name: "Passenger A", phone_number: "+919999999999", normalized_phone_number: "+919999999999",
      imported_fields: { booking_reference: "TRIP-001" }, welcome_delivered: true, welcome_status: "delivered",
      message_statuses: [{ message_type: "welcome", status: "delivered", already_sent: true, latest_resend_status: null, resend_blocked: false, submitted_at: "2026-09-18T09:00:00Z", status_updated_at: "2026-09-18T09:01:00Z" }],
    }],
    support_contacts: [{ id: "support-a", name: "Travel support", phone_number: "+919999999998", normalized_phone_number: "+919999999998" }],
    rejected_contact_count: 0,
  };
  const lifecycle: string[] = [];
  const unexpectedMutations: string[] = [];
  await page.context().addCookies([{ name: "access_token", value: "e2e-session", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/v1/auth/refresh") return json(route, { status: "authenticated", user: staff, token_type: "bearer", access_token_expires_at: "2099-09-19T13:00:00Z" });
    if (path === "/api/v1/auth/me") return json(route, staff);
    if (path === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (path === "/api/v1/whatsapp/groups" && request.method() === "GET") return json(route, group.is_archived === (url.searchParams.get("archived") === "true") ? [group] : []);
    if (path === "/api/v1/whatsapp/groups/broadcast-a" && request.method() === "GET") return json(route, group);
    if (path === "/api/v1/whatsapp/groups/broadcast-a/recipient-roster") return json(route, {
      items: group.recipients.map((recipient, display_order) => ({ kind: "recipient", recipient, display_order })),
      counts: { all: 1, sent: 1, failed: 0, rejected: 0, replaced: 0, unidentified: 0 },
    });
    if (request.method() === "POST" && ["/api/v1/whatsapp/groups/broadcast-a/archive", "/api/v1/whatsapp/groups/broadcast-a/restore"].includes(path)) {
      const archived = path.endsWith("/archive");
      lifecycle.push(archived ? "archive" : "restore");
      group = { ...group, is_archived: archived, archived_at: archived ? "2026-09-19T10:00:00Z" : null };
      return json(route, group);
    }
    if (path.endsWith("/message-catalog")) return json(route, catalog);
    if (request.method() === "GET") return json(route, []);
    unexpectedMutations.push(`${request.method()} ${path}`);
    return json(route, { detail: "No messaging or unrelated mutation is allowed in this test." }, 400);
  });
  return { lifecycle, unexpectedMutations };
}

for (const viewport of [{ name: "desktop", width: 1440, height: 1080 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`staff can archive, inspect read-only recipients, search and restore on ${viewport.name}`, async ({ page }, testInfo) => {
    const api = await mockBroadcastApi(page);
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.setViewportSize(viewport);
    await page.goto("/whatsapp");
    await page.getByRole("link", { name: "Open September travellers" }).click();
    await page.getByRole("link", { name: "Broadcast details", exact: true }).click();
    await expect(page.getByRole("button", { name: "Delete broadcast", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Archive broadcast", exact: true }).click();
    const confirmation = page.getByRole("dialog", { name: "Archive broadcast?" });
    await confirmation.getByRole("button", { name: "Archive broadcast", exact: true }).click();
    await expect(confirmation).toHaveCount(0);
    await expect(page.getByRole("textbox", { name: "Broadcast name", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Save changes", exact: true })).toBeDisabled();
    await page.getByRole("link", { name: "Recipients", exact: true }).click();
    await expect(page.getByText("Passenger A", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Add recipients", exact: true })).toBeDisabled();
    await expect(page.getByText("Delivered", { exact: true })).toBeVisible();
    await page.getByRole("searchbox", { name: "Search recipients", exact: true }).fill("missing passenger");
    await expect(page.getByText("No matching recipients", { exact: true })).toBeVisible();
    await page.getByRole("link", { name: "All broadcasts", exact: true }).click();
    await page.getByRole("button", { name: /^Archived/ }).click();
    await page.getByRole("searchbox", { name: "Search broadcasts", exact: true }).fill("does not exist");
    await expect(page.getByText("No broadcasts found", { exact: true })).toBeVisible();
    await page.getByRole("searchbox", { name: "Search broadcasts", exact: true }).fill("");
    await page.screenshot({ path: testInfo.outputPath(`archived-${viewport.name}.png`), fullPage: true, animations: "disabled" });
    await page.getByRole("link", { name: "Open September travellers" }).click();
    await page.getByRole("link", { name: "Broadcast details", exact: true }).click();
    await page.getByRole("button", { name: "Restore broadcast", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "Broadcast name", exact: true })).toBeEnabled();
    expect(api.lifecycle).toEqual(["archive", "restore"]);
    expect(api.unexpectedMutations).toEqual([]);
    expect(pageErrors).toEqual([]);
  });
}
