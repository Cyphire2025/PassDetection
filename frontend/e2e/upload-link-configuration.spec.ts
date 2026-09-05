import { expect, test, type Page, type Route } from "@playwright/test";
import type {
  CreateUploadLinkRequest,
  UpdateUploadLinkRequest,
  UploadLinkResponse,
} from "../features/passports/api/upload-links.api";

const admin = {
  id: "e2e-upload-settings-admin",
  email: "upload-settings@example.test",
  full_name: "Upload Settings Test Admin",
  role: "agency_admin",
  agency_id: "e2e-upload-settings-agency",
  is_active: true,
  last_login_at: null,
  created_at: "2026-09-05T00:00:00Z",
  updated_at: "2026-09-05T00:00:00Z",
  capabilities: [],
};

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockUploadLinkApi(page: Page) {
  const created: CreateUploadLinkRequest[] = [];
  const updated: UpdateUploadLinkRequest[] = [];
  const unexpectedMutations: string[] = [];
  let savedGroup: UploadLinkResponse | null = null;

  await page.context().addCookies([{
    name: "access_token",
    value: "e2e-session",
    domain: "127.0.0.1",
    path: "/",
    httpOnly: true,
    sameSite: "Lax",
  }]);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;
    if (pathname === "/api/v1/auth/refresh") {
      return json(route, {
        status: "authenticated",
        user: admin,
        token_type: "bearer",
        access_token_expires_at: "2099-09-05T13:00:00Z",
      });
    }
    if (pathname === "/api/v1/auth/me") return json(route, admin);
    if (pathname === "/api/v1/notifications/feed") {
      return json(route, { items: [], unread_count: 0, next_cursor: null });
    }
    if (pathname === "/api/v1/upload-links" && request.method() === "GET") {
      return json(route, url.searchParams.get("status_filter") === "archived" || !savedGroup ? [] : [savedGroup]);
    }
    if (pathname === "/api/v1/upload-links" && request.method() === "POST") {
      const body = request.postDataJSON() as CreateUploadLinkRequest;
      created.push(body);
      savedGroup = {
        ...body,
        id: "e2e-configured-upload-link",
        token: "e2e-configured-upload-token",
        agency_id: admin.agency_id,
        status: "active",
        created_by_user_id: admin.id,
        created_at: "2026-09-05T13:00:00Z",
        closed_at: null,
        package_name: null,
        departure_cities: body.departure_cities ?? [],
        qualifier_relation_options: [],
        notes: null,
        deleted_at: null,
        deleted_passport_count: 0,
        deletion_retained_records: false,
      };
      return json(route, savedGroup, 201);
    }
    if (pathname === "/api/v1/upload-links/e2e-configured-upload-link" && request.method() === "PATCH" && savedGroup) {
      const body = request.postDataJSON() as UpdateUploadLinkRequest;
      updated.push(body);
      savedGroup = { ...savedGroup, ...body };
      return json(route, savedGroup);
    }
    if (request.method() === "GET") return json(route, []);
    unexpectedMutations.push(`${request.method()} ${pathname}`);
    return json(route, { error: { code: "E2E_UNEXPECTED_MUTATION", message: "The test does not allow this mutation." } }, 400);
  });

  return { created, updated, unexpectedMutations, getSavedGroup: () => savedGroup };
}

for (const viewport of [
  { name: "desktop", width: 1440, height: 1080 },
  { name: "mobile", width: 390, height: 844 },
]) {
  test(`upload link configuration survives create and edit on ${viewport.name}`, async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    const api = await mockUploadLinkApi(page);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/upload-links");
    await expect(page.getByRole("heading", { name: "Group Links", level: 1 })).toBeVisible();
    await page.getByRole("button", { name: "Create Group Link", exact: true }).click();
    const createDialog = page.getByRole("dialog", { name: "Create Upload Link", exact: true });
    await expect(createDialog).toBeVisible();

    const sectionOrder = ["Group Details", "Visa Photo", "Passport", "Travel Preferences", "Professional Details", "Miscellaneous"];
    for (const [index, name] of sectionOrder.entries()) {
      await expect(createDialog.getByRole("heading", { level: 3 }).nth(index)).toHaveText(name);
    }
    await expect(createDialog.getByLabel("Notes", { exact: true })).toHaveCount(0);
    await expect(createDialog.getByRole("switch", { name: /Live Photo Capture/ })).toHaveCount(0);
    await createDialog.getByRole("textbox", { name: "Group Name", exact: true }).fill("Autumn Producer Group");
    await createDialog.getByRole("textbox", { name: "Destination", exact: true }).fill("Dubai");
    await createDialog.getByLabel(/Travel\/Departure Date/).fill("2026-11-01");
    await createDialog.getByLabel(/Return Date/).fill("2026-11-08");

    await createDialog.getByRole("switch", { name: "Enable Visa Photo", exact: true }).click();
    await expect(createDialog.getByRole("switch", { name: "Disable Live Photo Capture", exact: true })).toBeChecked();
    await expect(createDialog.getByRole("switch", { name: "Disable Photo Upload", exact: true })).toBeChecked();
    await createDialog.getByRole("switch", { name: "Disable Live Photo Capture", exact: true }).click();
    await createDialog.getByRole("checkbox", { name: "Make Visa Photo compulsory", exact: true }).uncheck();
    await createDialog.getByRole("heading", { name: "Group Details", exact: true }).scrollIntoViewIfNeeded();
    const screenshotPath = testInfo.outputPath(`upload-link-create-${viewport.name}.png`);
    await createDialog.screenshot({ path: screenshotPath, animations: "disabled" });
    await testInfo.attach(`Create upload link — ${viewport.name}`, { path: screenshotPath, contentType: "image/png" });
    const dialogBounds = await createDialog.boundingBox();
    expect(dialogBounds).not.toBeNull();
    expect(dialogBounds!.x).toBeGreaterThanOrEqual(0);
    expect(dialogBounds!.x + dialogBounds!.width).toBeLessThanOrEqual(viewport.width);

    await createDialog.getByText(/^Pages to request/).click();
    await expect(createDialog.getByRole("checkbox", { name: /^Personal Details Page/ })).toBeChecked();
    await expect(createDialog.getByRole("checkbox", { name: /^Address Details Page/ })).toBeChecked();
    await expect(createDialog.getByRole("checkbox", { name: /^Passport Front Cover/ })).not.toBeChecked();
    await createDialog.getByRole("checkbox", { name: /^Passport Front Cover/ }).check();
    await createDialog.getByRole("checkbox", { name: /^Passport Back Cover/ }).check();
    await createDialog.getByRole("checkbox", { name: "Make Passport compulsory", exact: true }).uncheck();
    await createDialog.getByRole("switch", { name: "Enable Base City", exact: true }).click();
    await createDialog.getByRole("checkbox", { name: "Make Base City compulsory", exact: true }).uncheck();
    await createDialog.getByRole("switch", { name: "Enable Agent/Employee Code", exact: true }).click();
    await createDialog.getByRole("textbox", { name: "Code field label", exact: true }).fill("Producer Code");
    await createDialog.getByRole("checkbox", { name: "Make Agent/Employee Code compulsory", exact: true }).uncheck();
    await createDialog.getByRole("switch", { name: "Enable Agency/Dealership Name", exact: true }).click();
    await createDialog.getByRole("textbox", { name: "Organisation field label", exact: true }).fill("Producer Company");
    await createDialog.getByRole("switch", { name: "Enable Staff Code", exact: true }).click();
    await expect(createDialog.getByRole("textbox", { name: /Staff Code/ })).toHaveCount(0);
    await expect(createDialog.getByRole("combobox", { name: /Agent or Employee/ })).toHaveCount(0);

    await createDialog.getByRole("button", { name: "Add custom question", exact: true }).click();
    await createDialog.getByRole("textbox", { name: "Question or activity name", exact: true }).fill("Excursion");
    await createDialog.getByRole("textbox", { name: "Option 1 for Excursion", exact: true }).fill("Museum");
    await createDialog.getByRole("textbox", { name: "Option 2 for Excursion", exact: true }).fill("Beach");
    await createDialog.getByRole("checkbox", { name: "Make Excursion compulsory", exact: true }).uncheck();
    await createDialog.getByRole("button", { name: "Add custom detail", exact: true }).click();
    await createDialog.getByRole("textbox", { name: "Custom heading", exact: true }).fill("Membership Number");
    await createDialog.getByRole("checkbox", { name: "Make Membership Number compulsory", exact: true }).uncheck();
    await createDialog.getByRole("button", { name: "Generate Links", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Links Generated", exact: true })).toBeVisible();
    expect(api.created).toHaveLength(1);
    const created = api.created[0];
    expect(created).not.toHaveProperty("notes");
    expect(created).toMatchObject({
      name: "Autumn Producer Group",
      require_selfie: true,
      base_city_enabled: true,
      agent_employee_code_enabled: true,
      staff_code_enabled: true,
      agency_dealership_name_enabled: true,
      upload_configuration: {
        passport_enabled: true,
        passport_required: false,
        passport_live_scan: true,
        passport_upload_pages: ["cover", "back_cover", "front", "back"],
        visa_photo_required: false,
        visa_photo_live_capture: false,
        visa_photo_upload: true,
        agent_employee_code_label: "Producer Code",
        agency_dealership_name_label: "Producer Company",
        required_fields: { base_city: false, agent_employee_code: false },
      },
      custom_questions: [{ label: "Excursion", options: ["Museum", "Beach"], enabled: true, required: false }],
      custom_details: [{ label: "Membership Number", enabled: true, required: false }],
    });
    await page.getByRole("button", { name: "Done", exact: true }).click();

    await page.getByRole("button", { name: "Edit", exact: true }).click();
    const editDialog = page.getByRole("dialog", { name: "Edit Group", exact: true });
    await expect(editDialog.getByRole("textbox", { name: "Code field label", exact: true })).toHaveValue("Producer Code");
    await expect(editDialog.getByRole("textbox", { name: "Organisation field label", exact: true })).toHaveValue("Producer Company");
    await expect(editDialog.getByRole("switch", { name: "Enable Live Photo Capture", exact: true })).not.toBeChecked();
    await expect(editDialog.getByRole("checkbox", { name: "Make Passport compulsory", exact: true })).not.toBeChecked();
    await expect(editDialog.getByRole("checkbox", { name: "Make Excursion compulsory", exact: true })).not.toBeChecked();
    await expect(editDialog.getByRole("checkbox", { name: "Make Membership Number compulsory", exact: true })).not.toBeChecked();
    await editDialog.getByText(/^Pages to request/).click();
    await expect(editDialog.getByRole("checkbox", { name: /^Passport Front Cover/ })).toBeChecked();
    await expect(editDialog.getByRole("checkbox", { name: /^Passport Back Cover/ })).toBeChecked();
    await editDialog.getByRole("textbox", { name: "Code field label", exact: true }).fill("Advisor Code");
    await editDialog.getByRole("checkbox", { name: "Make Visa Photo compulsory", exact: true }).check();
    await editDialog.getByRole("button", { name: "Save changes", exact: true }).click();
    await expect(editDialog).toHaveCount(0);
    expect(api.updated).toHaveLength(1);
    expect(api.updated[0]).toMatchObject({
      upload_configuration: { ...created.upload_configuration, agent_employee_code_label: "Advisor Code", visa_photo_required: true },
      custom_questions: created.custom_questions,
      custom_details: created.custom_details,
    });

    // A new document fetch proves persistence beyond the dialog's local state.
    await page.reload();
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    const reopened = page.getByRole("dialog", { name: "Edit Group", exact: true });
    await expect(reopened.getByRole("textbox", { name: "Code field label", exact: true })).toHaveValue("Advisor Code");
    await expect(reopened.getByRole("textbox", { name: "Organisation field label", exact: true })).toHaveValue("Producer Company");
    await expect(reopened.getByRole("checkbox", { name: "Make Visa Photo compulsory", exact: true })).toBeChecked();
    await expect(reopened.getByRole("checkbox", { name: "Make Agent/Employee Code compulsory", exact: true })).not.toBeChecked();
    await expect(reopened.getByRole("checkbox", { name: "Make Excursion compulsory", exact: true })).not.toBeChecked();
    await expect(reopened.getByRole("checkbox", { name: "Make Membership Number compulsory", exact: true })).not.toBeChecked();
    expect(api.getSavedGroup()?.upload_configuration?.passport_upload_pages).toEqual(["cover", "back_cover", "front", "back"]);
    expect(api.unexpectedMutations).toEqual([]);
  });
}
