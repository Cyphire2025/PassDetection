import { expect, test, type Page, type Route } from "@playwright/test";

const groupName = "Synthetic source preservation";
const originalBytes = "SYNTHETIC ORIGINAL SOURCE FOR 700 TRAVELLER ROWS";
const preview = { recipient_count: 1, accepted_count: 1, recipients: [{ name: "Original delivery contact", phone_number: "+919999999999", imported_fields: {} }], rejected_count: 699, rejected_counts: { duplicate_phone: 699 }, rejected_rows_truncated: true, omitted_rejected_count: 199, rejected_rows: Array.from({ length: 500 }, (_, index) => ({ sheet_name: "Travellers", row_number: index + 3, raw_name: `Synthetic Traveller ${index + 2}`, raw_phone_number: "+919999999999", reason_code: "duplicate_phone", reason: "Shared delivery number", imported_fields: {} })), available_matching_fields: [] };
const json = (route: Route, body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
async function setup(page: Page, existing: boolean) {
  const user = { id: "import-admin", email: "import@example.test", full_name: "Import Admin", role: "agency_admin", agency_id: "import-agency", is_active: true, capabilities: [] };
  const mutations: string[] = [];
  const group = { id: "import-group", name: groupName, is_archived: false, archived_at: null, created_at: "2026-10-13T00:00:00Z", updated_at: "2026-10-13T00:00:00Z", recipient_count: 0, total_contact_count: 0, recipient_opt_in_confirmed: true, linked_client_groups: [], rejected_contact_count: 0, support_contacts: [], recipients: [] };
  await page.context().addCookies([{ name: "access_token", value: "synthetic-import-session", domain: "127.0.0.1", path: "/", httpOnly: true }]);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    if (path === "/api/v1/auth/me") return json(route, user);
    if (path === "/api/v1/auth/refresh") return json(route, { status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (path === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (path === "/api/v1/whatsapp/contacts/preview") return json(route, preview);
    if (path === "/api/v1/whatsapp/groups" && request.method() === "GET") return json(route, existing ? [group] : []);
    if (path === "/api/v1/whatsapp/groups/import-group") return json(route, group);
    if (path.endsWith("/recipient-roster")) return json(route, { items: [], counts: { all: 0, sent: 0, failed: 0, rejected: 0, replaced: 0, unidentified: 0 } });
    if (request.method() === "POST" && ["/api/v1/whatsapp/groups", "/api/v1/whatsapp/groups/import-group/recipients"].includes(path)) { mutations.push(request.postData() ?? ""); return json(route, group); }
    if (request.method() === "GET") return json(route, []);
    return route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: "Unexpected synthetic mutation blocked" }) });
  });
  return mutations;
}

for (const operation of ["create", "add"] as const) test(`700-person import retains the original source and edited recipient in ${operation}`, async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  const mutations = await setup(page, operation === "add");
  await page.goto("/whatsapp");
  if (operation === "create") await page.getByRole("button", { name: "Create Broadcast", exact: true }).first().click();
  else {
    await page.getByRole("button", { name: `Open actions for ${groupName}` }).filter({ visible: true }).click();
    await page.getByRole("button", { name: "Recipient List", exact: true }).click();
    await page.getByRole("navigation", { name: "Broadcast workspace" }).getByRole("button", { name: /^Add recipients/ }).click();
  }
  const dialog = page.getByRole("dialog");
  if (operation === "create") {
    await dialog.getByRole("textbox", { name: "Group name", exact: true }).fill(groupName);
    const support = dialog.locator("section").filter({ has: page.getByRole("heading", { name: "Passport-link support contacts", exact: true }) });
    await support.getByRole("textbox", { name: "Name", exact: true }).fill("Support");
    await support.getByRole("textbox", { name: "WhatsApp number", exact: true }).fill("+917777777777");
    await support.getByRole("button", { name: "Add", exact: true }).click();
  }
  await dialog.locator('input[type="file"]').setInputFiles({ name: "700-travellers.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from(originalBytes) });
  await expect(dialog.getByRole("heading", { name: "699 spreadsheet rows need attention" })).toBeVisible();
  await expect(dialog.getByText(/original workbook is retained/)).toBeVisible();
  if (operation === "add") await expect(dialog.getByRole("navigation", { name: "Broadcast workspace" }).getByRole("button", { name: /^Add recipients/ })).toContainText("700");
  await dialog.getByRole("textbox", { name: "Recipient 1 name", exact: true }).fill("Reviewed delivery contact");
  await dialog.getByRole("checkbox", { name: /recipients agreed/ }).check();
  await dialog.getByRole("button", { name: operation === "create" ? "Save List" : "Add Recipients", exact: true }).click();
  await expect.poll(() => mutations.length).toBe(1);
  expect(mutations[0]).toContain('name="duplicate_source_files"; filename="700-travellers.xlsx"');
  expect(mutations[0]).toContain(originalBytes);
  expect(mutations[0]).toContain('"name":"Reviewed delivery contact"');
  expect(mutations[0]).not.toContain('name="contacts_file"');
});
