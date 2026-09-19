import { expect, test, type Page, type Route } from "@playwright/test";
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
    if (request.method() === "GET") return json(route, []);
    unexpectedMutations.push(`${request.method()} ${path}`);
    return json(route, { detail: "No messaging or unrelated mutation is allowed in this test." }, 400);
  });
  return { lifecycle, unexpectedMutations };
}

for (const viewport of [{ name: "desktop", width: 1440, height: 1080 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`staff can archive, inspect read-only history, search and restore on ${viewport.name}`, async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    const api = await mockBroadcastApi(page);
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.setViewportSize(viewport);
    await page.goto("/whatsapp");
    const active = page.getByRole("region", { name: "Active broadcasts", exact: true });
    const archived = page.getByRole("region", { name: "Archived broadcasts", exact: true });
    await active.getByRole("button", { name: "Open actions for September travellers" }).filter({ visible: true }).click();
    await expect(page.getByRole("button", { name: "Delete Broadcast", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Archive Broadcast", exact: true }).click();
    const confirmation = page.getByRole("dialog", { name: "Archive WhatsApp broadcast?" });
    await expect(confirmation).toContainText("delivery history will be retained");
    await confirmation.getByRole("button", { name: "Archive Broadcast", exact: true }).click();
    await expect(confirmation).toHaveCount(0);
    await expect(active.getByText("No active broadcasts", { exact: true })).toBeVisible();
    await archived.scrollIntoViewIfNeeded();
    await archived.getByRole("button", { name: "Open actions for September travellers" }).filter({ visible: true }).click();
    await expect(page.getByRole("button", { name: "Send Reminder", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Restore Broadcast", exact: true })).toBeVisible();
    const archiveScreenshot = testInfo.outputPath(`whatsapp-archive-${viewport.name}.png`);
    await page.screenshot({ path: archiveScreenshot, animations: "disabled", fullPage: true });
    await testInfo.attach(`Archived broadcasts — ${viewport.name}`, { path: archiveScreenshot, contentType: "image/png" });
    await page.getByRole("button", { name: "Recipient List", exact: true }).click();
    const recipients = page.getByRole("dialog", { name: "Recipients — September travellers" });
    await expect(recipients.getByText("Passenger A", { exact: true })).toBeVisible();
    await expect(recipients.getByText(/This broadcast is archived and read-only/)).toBeVisible();
    await expect(recipients.getByRole("button", { name: "Add recipients", exact: true })).toHaveCount(0);
    await expect(recipients.getByRole("checkbox", { name: "Select Passenger A" })).toBeDisabled();
    await expect(recipients.getByText("Sent", { exact: true })).toBeVisible();
    await recipients.getByRole("searchbox", { name: "Search current recipients" }).fill("missing passenger");
    await expect(recipients.getByText(/No recipients match/)).toBeVisible();
    await recipients.getByRole("searchbox", { name: "Search current recipients" }).fill("");
    await recipients.getByRole("button", { name: "Broadcast details", exact: true }).click();
    await expect(recipients.getByRole("textbox", { name: "Group name", exact: true })).toBeDisabled();
    await expect(recipients.getByRole("button", { name: "Save Details", exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(recipients).toHaveCount(0);
    await page.getByRole("searchbox", { name: "Search WhatsApp broadcast groups" }).fill("does not exist");
    await expect(archived.getByText("No archived broadcasts match this search")).toBeVisible();
    await page.getByRole("searchbox", { name: "Search WhatsApp broadcast groups" }).fill("");
    await archived.getByRole("button", { name: "Open actions for September travellers" }).filter({ visible: true }).click();
    await page.getByRole("button", { name: "Restore Broadcast", exact: true }).click();
    await expect(archived.getByText("No archived broadcasts", { exact: true })).toBeVisible();
    await active.getByRole("button", { name: "Open actions for September travellers" }).filter({ visible: true }).click();
    await expect(page.getByRole("button", { name: "Send Reminder", exact: true })).toBeEnabled();
    expect(api.lifecycle).toEqual(["archive", "restore"]);
    expect(api.unexpectedMutations).toEqual([]);
    expect(pageErrors).toEqual([]);
  });
}
