import { expect, test, type Page, type Route } from "@playwright/test";

const sourceId = "00000000-0000-4000-8000-000000000101";
const emptyId = "00000000-0000-4000-8000-000000000102";
const sourceName = "Dubai September Delegates";
const recipients = [
  { name: "Nisha Kapoor", phone_number: "+919900001234", imported_fields: {} },
  { name: "Aarav Shah", phone_number: "+919900001235", imported_fields: {} },
];
const preview = {
  source_group_id: sourceId, source_group_name: sourceName,
  total_submissions: 5, recipient_count: 2, recipients, excluded_count: 3,
  excluded_counts: { missing_phone: 1, invalid_phone: 1, unverified_phone: 0, missing_name: 0, name_too_long: 0, duplicate_phone: 1 },
  preview_revision: "a".repeat(64),
};

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function setup(page: Page) {
  const user = { id: "source-admin", email: "source@example.test", full_name: "Group Test Admin", role: "agency_admin", agency_id: "source-agency", is_active: true, capabilities: [] };
  const requests: Record<string, unknown>[] = [];
  const unexpectedMutations: string[] = [];
  const pageErrors: string[] = [];
  let created = false;
  const group = {
    id: "new-broadcast", name: sourceName, is_archived: false, archived_at: null,
    created_at: "2026-09-21T00:00:00Z", updated_at: "2026-09-21T00:00:00Z",
    recipient_count: 2, total_contact_count: 2, recipient_opt_in_confirmed: true,
    rejected_contact_count: 0, support_contacts: [],
    recipients: recipients.map((recipient, index) => ({ ...recipient, id: `recipient-${index}`, normalized_phone_number: recipient.phone_number, welcome_status: null, welcome_delivered: false, message_statuses: [] })),
  };
  page.on("pageerror", error => pageErrors.push(error.message));
  await page.context().addCookies([{ name: "access_token", value: "e2e-session", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  await page.route("**/api/v1/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/v1/auth/refresh") return json(route, { status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-09-21T00:00:00Z" });
    if (path === "/api/v1/auth/me") return json(route, user);
    if (path === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (path === "/api/v1/whatsapp/groups" && request.method() === "GET") return json(route, created && url.searchParams.get("archived") !== "true" ? [group] : []);
    if (path === "/api/v1/whatsapp/source-groups") return json(route, [
      { id: sourceId, name: sourceName, submission_count: 5 },
      { id: emptyId, name: "Empty active group", submission_count: 0 },
    ]);
    if (path === `/api/v1/whatsapp/source-groups/${sourceId}/preview`) return json(route, preview);
    if (path === `/api/v1/whatsapp/source-groups/${emptyId}/preview`) return json(route, {
      ...preview, source_group_id: emptyId, source_group_name: "Empty active group", total_submissions: 0, recipient_count: 0,
      recipients: [], excluded_count: 0, excluded_counts: { missing_phone: 0, invalid_phone: 0, unverified_phone: 0, missing_name: 0, name_too_long: 0, duplicate_phone: 0 }, preview_revision: "b".repeat(64),
    });
    if (path === "/api/v1/whatsapp/groups/from-client-group" && request.method() === "POST") {
      requests.push(request.postDataJSON());
      created = true;
      return json(route, { group, source: preview }, 201);
    }
    if (request.method() === "GET") return json(route, []);
    unexpectedMutations.push(`${request.method()} ${path}`);
    return json(route, { detail: "Unexpected mutation in isolated group creation test" }, 400);
  });
  return { requests, unexpectedMutations, pageErrors };
}

for (const viewport of [{ name: "desktop", width: 1440, height: 1080 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`create a broadcast from a group on ${viewport.name}`, async ({ page }, testInfo) => {
    const state = await setup(page);
    await page.setViewportSize(viewport);
    await page.goto("/whatsapp");
    await page.getByRole("button", { name: "Create Broadcast", exact: true }).first().click();
    const dialog = page.getByRole("dialog", { name: "Create WhatsApp Broadcast Group" });
    await dialog.getByRole("radio", { name: "Create from existing group" }).check();
    await dialog.getByRole("combobox", { name: "Existing group" }).selectOption(sourceId);
    await expect(dialog.getByText("Nisha Kapoor", { exact: true })).toBeVisible();
    await expect(dialog.getByText("Aarav Shah", { exact: true })).toBeVisible();
    await expect(dialog.getByText("+919900001234", { exact: true })).toBeVisible();
    await expect(dialog.getByRole("textbox", { name: "Group name", exact: true })).toHaveValue(sourceName);
    await dialog.getByRole("button", { name: "Save List", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText("Add at least one customer support contact.");
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`source-group-${viewport.name}.png`), fullPage: true, animations: "disabled" });

    const support = dialog.locator("section").filter({ has: page.getByRole("heading", { name: "Passport-link support contacts", exact: true }) });
    await support.getByRole("textbox", { name: "Name", exact: true }).fill("Travel Support");
    await support.getByRole("textbox", { name: "WhatsApp number", exact: true }).fill("+919900001299");
    await support.getByRole("button", { name: "Add", exact: true }).click();
    await dialog.getByRole("checkbox", { name: /I confirm these recipients agreed/ }).check();
    await dialog.getByRole("button", { name: "Save List", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    expect(state.requests).toHaveLength(1);
    expect(state.requests[0]).toMatchObject({
      source_group_id: sourceId, name: sourceName, preview_revision: preview.preview_revision,
      recipient_opt_in_confirmed: true, support_contacts: [{ name: "Travel Support", phone_number: "+919900001299" }],
    });
    expect(state.requests[0]).not.toHaveProperty("contacts");
    expect(state.unexpectedMutations).toEqual([]);
    expect(state.pageErrors).toEqual([]);
  });
}

test("switching to an empty source clears the previous recipients and blocks creation", async ({ page }) => {
  const state = await setup(page);
  await page.goto("/whatsapp");
  await page.getByRole("button", { name: "Create Broadcast", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "Create WhatsApp Broadcast Group" });
  await dialog.getByRole("radio", { name: "Create from existing group" }).check();
  await dialog.getByRole("combobox", { name: "Existing group" }).selectOption(sourceId);
  await expect(dialog.getByText("Nisha Kapoor", { exact: true })).toBeVisible();
  await dialog.getByRole("combobox", { name: "Existing group" }).selectOption(emptyId);
  await expect(dialog.getByText("Nisha Kapoor", { exact: true })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "Save List", exact: true })).toBeDisabled();
  expect(state.requests).toEqual([]);
  expect(state.unexpectedMutations).toEqual([]);
});
