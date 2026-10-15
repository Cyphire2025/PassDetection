import { expect, test, type Route } from "@playwright/test";

test("selected passenger display name can be edited and restored independently of passport identity", async ({ page }) => {
  const groupId = "display-name-group";
  const updated = "2026-10-16T04:00:00Z";
  const user = { id: "office-user", email: "staff@example.test", full_name: "Office staff",
    role: "agency_admin", agency_id: "office-agency", is_active: true, capabilities: [] };
  const passengers = ["first", "second"].map((id, index) => ({
    id, group_id: groupId, agency_id: user.agency_id, client_name: "SHIVANAND", display_name: null as string | null,
    client_email: `${id}@example.test`, client_phone: null, departure_city: null,
    image_s3_key: "excel-imports/synthetic", status: "staff_approved", extraction_status: "extraction_complete",
    extraction_revision: 1, created_at: updated, updated_at: updated,
    confirmed_fields: { given_names: "SHIVANAND", surname: "", passport_number: `P123456${index}`, nationality: "Indian" },
    extracted_fields: {}, overall_confidence: 1,
  }));
  const patches: unknown[] = [];
  const unexpected: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.context().addCookies([{ name: "access_token", value: "isolated-display-name-test", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/auth/refresh") return json(route, { status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (path === "/api/v1/auth/me") return json(route, user);
    if (path === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (path === "/api/v1/passports/groups") return json(route, [{
      group_id: groupId, group_name: "Synthetic same-name passengers", group_status: "active",
      total_passports: 2, pending_review_count: 0, confirmed_count: 2, failed_count: 0,
      latest_submission_at: updated, destination: "Dubai", travel_date: "2026-10-22", return_date: "2026-10-28",
      timezone: "Asia/Dubai", package_name: null, departure_cities: [], notes: null, custom_questions: [], custom_details: [],
    }]);
    if (path.endsWith("/submissions-view")) return json(route, {
      items: passengers, ordered_submission_ids: passengers.map((person) => person.id),
      ordered_selection_snapshot: passengers.map((person) => ({ id: person.id, extraction_revision: 1, updated_at: person.updated_at })),
      group_total: 2, total: 2, page: 1, page_size: 50, total_pages: 1, returned_count: 2,
      duplicate_clusters: [], expiry_alerts: [], cluster_boundaries_preserved: true,
    });
    if (path.endsWith("/whatsapp-links")) return json(route, { client_group_id: groupId, can_manage: true, recipient_count: 0, broadcast_count: 0, broadcasts: [] });
    if (path.endsWith("/whatsapp-deliveries/tracking")) return json(route, { group_id: groupId, poll_after_seconds: null, counts: { total: 0, queued: 0, sent: 0, delivered: 0, read: 0, failed: 0, delivery_unknown: 0 }, deliveries: [] });
    if (path === "/api/v1/passports/first") return json(route, passengers[0]);
    if (request.method() === "PATCH" && path === `/api/v1/passports/groups/${groupId}/submissions/first/display-name`) {
      const body = request.postDataJSON();
      patches.push(body);
      if (body.expected_updated_at !== passengers[0].updated_at) return json(route, { detail: "Conflict" }, 409);
      passengers[0].display_name = body.display_name === passengers[0].client_name ? null : body.display_name;
      passengers[0].updated_at = `2026-10-16T04:0${patches.length}:00Z`;
      return json(route, { id: "first", client_name: "SHIVANAND", display_name: passengers[0].display_name, updated_at: passengers[0].updated_at });
    }
    if (request.method() === "GET") return json(route, []);
    unexpected.push(`${request.method()} ${path}`);
    return json(route, { detail: "Unexpected mutation" }, 400);
  });
  await page.goto(`/passports/groups/${groupId}`);
  await expect(page.getByRole("checkbox", { name: "Select SHIVANAND", exact: true })).toHaveCount(2);
  await page.getByRole("checkbox", { name: "Select SHIVANAND", exact: true }).first().check();
  await page.getByRole("button", { name: "Open bulk actions for 1 selected submissions" }).click();
  await page.getByRole("button", { name: "Edit display name", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Edit display name" });
  await dialog.getByRole("textbox", { name: "Display name", exact: true }).fill("SHIVANAND A");
  await dialog.getByRole("button", { name: "Save display name" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Select SHIVANAND A", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "P1234560 Indian", exact: true })).toBeVisible();
  expect(patches).toEqual([{ display_name: "SHIVANAND A", expected_updated_at: updated }]);

  await page.getByRole("button", { name: "Open bulk actions for 1 selected submissions" }).click();
  await page.getByRole("button", { name: "Edit display name", exact: true }).click();
  await expect(dialog.getByRole("textbox", { name: "Display name", exact: true })).toHaveValue("SHIVANAND A");
  await dialog.getByRole("textbox", { name: "Display name", exact: true }).fill("SHIVANAND");
  await dialog.getByRole("button", { name: "Save display name" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Select SHIVANAND", exact: true })).toHaveCount(2);
  expect(passengers[0].confirmed_fields.given_names).toBe("SHIVANAND");
  expect(passengers[1].display_name).toBeNull();
  expect(patches).toHaveLength(2);
  expect(unexpected).toEqual([]);
  expect(errors).toEqual([]);
});
