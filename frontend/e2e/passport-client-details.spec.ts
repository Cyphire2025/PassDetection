import { expect, test, type Page, type Route } from "@playwright/test";

const id = "client-details-passport";
const groupId = "client-details-group";
const updatedAt = "2026-09-11T00:00:00Z";
const user = {
  id: "details-admin", agency_id: "details-agency", role: "agency_admin",
  full_name: "Review Team", email: "review@example.test", is_active: true,
  capabilities: [], created_at: updatedAt, updated_at: updatedAt, last_login_at: null,
};

async function installFixture(page: Page, conflict = false) {
  const writes: Record<string, unknown>[] = [];
  const unexpected: string[] = [];
  const passport = {
    id, group_id: groupId, agency_id: user.agency_id, client_name: "Sample Traveller",
    client_email: "traveller@example.test", client_phone: "9876543210",
    departure_city: "Mumbai", nearest_domestic_airport: null,
    submission_mode: "single", family_group_id: null, image_s3_key: "test/front.jpg",
    image_url: null, passport_photo_url: null, passport_back_url: null,
    passport_photo_s3_key: null, passport_back_s3_key: null,
    staff_metadata: { agent_employee_code_label: "Producer Code", agency_dealership_name_label: "Producer Name" },
    custom_answers: [], custom_detail_answers: [], status: "ai_approved",
    extracted_fields: {}, confirmed_fields: {
      agent_employee_code: "AIG12345", agency_dealership_name: "Qualified Person",
      passport_number: "X1234567", given_names: "SAMPLE", surname: "TRAVELLER",
    },
    extraction_status: "ready_for_review", extraction_revision: 2,
    extraction_conflicts: [], post_submission_verification: null,
    duplicate_cluster_size: 1, duplicate_cluster_member_ids: [], duplicate_cluster_id: null,
    processing_job_status: "succeeded", processing_progress: 100,
    client_reviewed_at: updatedAt, created_at: updatedAt, updated_at: updatedAt,
  };
  await page.context().addCookies([{
    name: "access_token", value: "isolated-details-test", domain: "127.0.0.1",
    path: "/", httpOnly: true, sameSite: "Lax",
  }]);
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({
    status, contentType: "application/json", body: JSON.stringify(body),
  });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/auth/refresh") return json(route, {
      status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z",
    });
    if (path === "/api/v1/auth/me") return json(route, user);
    if (path === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (path.startsWith("/api/v1/telemetry")) return json(route, {});
    if (path === `/api/v1/passports/${id}`) return json(route, passport);
    if (path === `/api/v1/passports/${id}/client-details`) {
      if (request.method() === "PATCH") {
        const body = request.postDataJSON() as Record<string, unknown>;
        writes.push(body);
        if (conflict) return json(route, { detail: "This submission changed. Reload the latest details before saving." }, 409);
        passport.confirmed_fields.agent_employee_code = String(body.agent_employee_code);
        passport.updated_at = "2026-09-11T00:01:00Z";
        return json(route, passport);
      }
      return json(route, {
        updated_at: passport.updated_at,
        fields: [
          { key: "client_email", label: "Email entered by client", value: passport.client_email, type: "email", required: false, options: [], max_length: 254 },
          { key: "client_phone", label: "Phone entered by client", value: passport.client_phone, type: "tel", required: false, options: [], max_length: 32 },
          { key: "agent_employee_code", label: "Producer Code", value: passport.confirmed_fields.agent_employee_code, type: "text", required: true, options: [], max_length: 80 },
          { key: "agency_dealership_name", label: "Producer Name", value: "Qualified Person", type: "text", required: true, options: [], max_length: 200 },
          { key: "departure_city", label: "Nearest international airport", value: "Mumbai", type: "select", required: true, options: ["Mumbai", "Delhi"], max_length: 120 },
        ],
        custom_answers: [{ question_id: "11111111-1111-4111-8111-111111111111", label: "Meal preference", value: "Veg", required: true, options: ["Veg", "Non Veg"], max_length: 120 }],
        custom_detail_answers: [{ detail_id: "22222222-2222-4222-8222-222222222222", label: "Office location", value: "Mumbai", required: false, max_length: 500 }],
      });
    }
    unexpected.push(`${request.method()} ${path}`);
    return json(route, { detail: "Unexpected isolated test request" }, 400);
  });
  return { writes, unexpected };
}

for (const width of [1440, 390]) {
  test(`client details correction preserves passport approval and saves only edits at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width < 600 ? 844 : 1000 });
    const fixture = await installFixture(page);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    await page.goto(`/passports/${id}`);
    await expect(page.getByRole("heading", { name: "Sample Traveller", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Edit client-provided group details" }).click();
    const dialog = page.getByRole("dialog", { name: "Edit client-provided group details" });
    await expect(dialog.getByLabel("Producer Code")).toHaveValue("AIG12345");
    await expect(dialog.getByRole("button", { name: "Save corrections" })).toBeDisabled();
    await dialog.getByLabel("Producer Code").fill("12345");
    await expect(dialog.getByLabel("Meal preference")).toHaveValue("Veg");
    await expect(dialog.getByLabel("Office location")).toHaveValue("Mumbai");
    const bounds = await dialog.locator("form").boundingBox();
    expect(bounds!.width).toBeLessThanOrEqual(width);
    await expect(dialog.getByRole("button", { name: "Save corrections" })).toBeInViewport();
    await page.screenshot({ path: `test-results/client-details-editor-${width}.png`, fullPage: true });
    await dialog.getByRole("button", { name: "Save corrections" }).click();
    await expect(dialog).toBeHidden();
    expect(fixture.writes).toEqual([{ expected_updated_at: updatedAt, agent_employee_code: "12345" }]);
    await expect(page.getByText("12345", { exact: true })).toBeVisible();
    await expect(page.getByText("AI Approved", { exact: true }).first()).toBeVisible();
    expect(errors).toEqual([]);
    expect(fixture.unexpected).toEqual([]);
  });
}

test("cancel discards edits and a stale save keeps the draft for explicit reload", async ({ page }) => {
  const fixture = await installFixture(page, true);
  await page.goto(`/passports/${id}`);
  await page.getByRole("button", { name: "Edit client-provided group details" }).click();
  const dialog = page.getByRole("dialog", { name: "Edit client-provided group details" });
  await dialog.getByLabel("Producer Code").fill("discard-this");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(fixture.writes).toHaveLength(0);
  await page.getByRole("button", { name: "Edit client-provided group details" }).click();
  await expect(dialog.getByLabel("Producer Code")).toHaveValue("AIG12345");
  await dialog.getByLabel("Producer Code").fill("12345");
  await dialog.getByRole("button", { name: "Save corrections" }).click();
  await expect(dialog.getByRole("button", { name: "Reload latest details" })).toBeVisible();
  await expect(dialog.getByLabel("Producer Code")).toHaveValue("12345");
  await expect(dialog.getByRole("button", { name: "Save corrections" })).toBeDisabled();
  expect(fixture.writes).toHaveLength(1);
  expect(fixture.unexpected).toEqual([]);
});
