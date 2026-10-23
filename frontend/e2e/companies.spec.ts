import { expect, test, type Page, type Route } from "@playwright/test";
import type { Company, CompanyReference } from "../features/companies/types";

const agencyId = "11111111-1111-4111-8111-111111111111";
const companyId = "22222222-2222-4222-8222-222222222222";
const personId = "44444444-4444-4444-8444-444444444444";
const company: Company = { id: companyId, name: "Enterprise Travel Client", status: "active", external_reference: "00017", revision: 3, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z" };
const user = { id: "33333333-3333-4333-8333-333333333333", agency_id: agencyId, email: "company-admin@example.test", full_name: "Company Admin", role: "agency_admin", is_active: true, created_at: company.created_at, updated_at: company.updated_at, last_login_at: null, capabilities: [] };
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z8ZkAAAAASUVORK5CYII=", "base64");
const respond = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function fixture(page: Page, role = "agency_admin") {
  let saved = { ...company };
  let removed = false;
  let policy = { company_id: companyId, enabled: false, revision: 0, notice_text: "Travellers verify their identity before reviewing saved documents." };
  let record = { id: personId, status: "active", display_name: "Example Traveller", revision: 4, contact_revision: 2, phone_number: "+919876543210", phone_verified: true, current_document: { id: "document", passport_id: "passport", revision_number: 2, issuing_country: "IND", document_type: "P", fields: { given_names: "Example", surname: "Traveller", passport_number: "A1234567", nationality: "IND", place_of_issue: "Mumbai", date_of_birth: "1990-01-01", date_of_issue: "2020-01-01", date_of_expiry: "2030-01-01", sex: "M" } } };
  let exported = false;
  const job = { id: "export-one", kind: "images", status: "succeeded", processed_count: 700, part_count: 2, created_at: company.created_at, expires_at: null, error_code: null };
  const requests: Array<{ path: string; method: string; body: unknown }> = [];
  await page.context().addCookies([{ name: "access_token", value: "synthetic-companies-test", domain: "127.0.0.1", path: "/", httpOnly: true }]);
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request(); const url = new URL(req.url()); const path = url.pathname;
    const body = req.headers()["content-type"]?.includes("application/json") ? req.postDataJSON() : null;
    requests.push({ path, method: req.method(), body });
    const currentUser = { ...user, role, agency_id: role === "super_admin" ? null : agencyId };
    if (path === "/api/v1/auth/me") return respond(route, currentUser);
    if (path === "/api/v1/auth/refresh") return respond(route, { status: "authenticated", user: currentUser, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (path === "/api/v1/notifications/feed") return respond(route, { items: [], unread_count: 0, next_cursor: null });
    if (path === "/api/v1/companies/workspace") return respond(route, { agency_id: agencyId });
    if (path === "/api/v1/companies/lookup") {
      const option: CompanyReference = url.searchParams.has("cursor") ? { id: companyId, name: "Company 251", status: "active" } : saved;
      return respond(route, { items: [option], next_cursor: url.searchParams.has("cursor") ? null : "opaque-page-2", has_more: !url.searchParams.has("cursor") });
    }
    if (path.startsWith("/api/v1/companies")) {
      expect(url.searchParams.get("agency_id")).toBe(agencyId);
      if (path.endsWith("/reuse-policy")) {
        if (req.method() === "PUT") { expect(Object.keys(body).sort()).toEqual(["enabled", "expected_revision"]); policy = { ...policy, enabled: body.enabled, revision: policy.revision + 1 }; saved.revision++; }
        return respond(route, policy);
      }
      if (path === `/api/v1/companies/${companyId}/summary`) return respond(route, { completed_groups: 2, current_groups: 1, passenger_trips_completed: 600, passenger_trips_total: 900, active_groups: 1, closed_groups: 1, archived_groups: 1, total_groups: 3, collected_records: 900, unique_travellers: 700, trip_participations: 900, unresolved_historical_records: 0, identity_totals_partial: false });
      if (path === `/api/v1/companies/${companyId}/groups`) {
        expect(url.searchParams.get("page_size")).toBe("25");
        expect(["active", "completed"]).toContain(url.searchParams.get("phase"));
        return respond(route, { items: [{ id: url.searchParams.get("phase") === "active" ? "active-trip" : "completed-trip", name: url.searchParams.get("phase") === "active" ? "Japan Autumn" : "Singapore Spring", destination: "Asia", travel_date: "2026-11-01", return_date: "2026-11-08", status: "archived", import_only: true, submission_count: 700, phase: url.searchParams.get("phase") }], next_cursor: null, has_more: false });
      }
      if (path.endsWith("/people")) { expect(url.searchParams.get("page_size")).toBe("100"); return respond(route, { items: [{ id: personId, display_name: record.display_name, status: "active", revision: record.revision, trip_count: 2, submission_count: 3, document_version_count: record.current_document.revision_number, duplicate_status: "possible", current_passport_last4: "4567" }], next_cursor: null, has_more: false }); }
      if (path.endsWith("/record")) {
        if (req.method() === "PATCH") { expect(body.expected_revision).toBe(record.revision); record = { ...record, display_name: body.display_name, revision: record.revision + 1 }; }
        return respond(route, record);
      }
      if (path.endsWith("/sources")) return respond(route, { items: [{ id: "source-new", group_id: "active-trip", group_name: "Japan Autumn", created_at: "2026-10-02T00:00:00Z", revision_number: 2, available_sides: ["front"] }, { id: "source-old", group_id: "completed-trip", group_name: "Singapore Spring", created_at: "2026-01-02T00:00:00Z", revision_number: 1, available_sides: [] }], next_cursor: null, has_more: false });
      if (path.endsWith("/documents")) {
        if (req.method() === "POST") {
          const metadataText = req.postData()?.match(/name="metadata"\r\n\r\n([^\r\n]+)\r\n/)?.[1];
          expect(metadataText).toBeTruthy(); const metadata = JSON.parse(metadataText!);
          expect(metadata).toMatchObject({ expected_revision: record.revision, change_kind: "scan", side: "front", issuing_country: "IND", document_type: "P" });
          expect(req.postData()).toContain('filename="updated.png"');
          record = { ...record, revision: record.revision + 1, current_document: { ...record.current_document, revision_number: 3 } };
          return respond(route, record, 201);
        }
        return respond(route, { items: [record.current_document.revision_number, 1].map((revision) => ({ id: `version-${revision}`, passport_id: "passport", revision_number: revision, status: "accepted", created_at: company.created_at, change_kind: "scan", is_current: revision === record.current_document.revision_number, fields: record.current_document.fields, assets: [{ id: `asset-${revision}`, side: "front", content_type: "image/png", byte_size: png.length, availability: "available" }] })), next_cursor: null, has_more: false });
      }
      if (path.includes("/assets/")) return route.fulfill({ status: 200, contentType: "image/png", body: png });
      if (path.endsWith("/data-exports")) {
        if (req.method() === "POST") { exported = true; return respond(route, { ...job, kind: body.kind, status: "queued" }, 202); }
        return respond(route, { items: exported ? [job] : [], next_cursor: null, has_more: false });
      }
      if (path.endsWith("/parts")) return respond(route, { items: [{ id: "part-1", part_number: 1, filename: "documents-001.zip", content_type: "application/zip", byte_size: 1000, record_count: 400 }], next_cursor: null, has_more: false });
      if (path === `/api/v1/companies/${companyId}`) {
        if (req.method() === "PATCH") { expect(body.expected_revision).toBe(saved.revision); saved = { ...saved, ...body, revision: saved.revision + 1 }; }
        if (req.method() === "DELETE") { removed = true; return route.fulfill({ status: 204 }); }
        return respond(route, saved);
      }
      if (req.method() === "POST") { saved = { ...saved, ...body, revision: 1 }; return respond(route, saved, 201); }
      return respond(route, { items: removed ? [] : [saved], next_cursor: null, has_more: false });
    }
    if (path === "/api/v1/upload-links" && req.method() === "POST") return respond(route, { id: "created-client-trip", token: "synthetic-client-trip-token", ...body }, 201);
    if (req.method() === "GET") return respond(route, []);
    return respond(route, { detail: "Unexpected test mutation blocked" }, 403);
  });
  return requests;
}

for (const width of [320, 1440]) {
  test(`compact companies, server group phases and saved-document setting work at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const requests = await fixture(page);
    const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/companies");
    await expect(page.getByRole("link", { name: `View company: ${company.name}` })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`companies-${width}.png`), fullPage: true });
    await page.getByRole("link", { name: `View company: ${company.name}` }).click();
    await expect(page.getByRole("heading", { name: company.name })).toBeVisible();
    await expect(page.getByRole("tab")).toHaveText(["Groups", "Settings", "All data"]);
    await expect(page.getByRole("region", { name: "Company overview" })).toContainText("Completed groups2Active groups1Passenger trips900Unique people700");
    await expect(page.getByRole("link", { name: "View Japan Autumn" })).toHaveAttribute("href", `/passports/groups/active-trip?returnTo=${encodeURIComponent(`/companies/${companyId}`)}`);
    await expect(page.getByRole("link", { name: "View Singapore Spring" })).toHaveAttribute("href", `/passports/groups/completed-trip?returnTo=${encodeURIComponent(`/companies/${companyId}`)}`);
    expect(requests.filter((request) => /reuse-policy|\/people/.test(request.path))).toHaveLength(0);
    const countBefore = requests.filter((request) => request.path.includes("/companies")).length;
    await page.evaluate(() => { window.dispatchEvent(new Event("blur")); window.dispatchEvent(new Event("focus")); });
    await page.getByRole("tab", { name: "Settings", exact: true }).click();
    const toggle = page.getByRole("switch", { name: "Use saved documents" });
    await expect(toggle).not.toBeChecked();
    await toggle.click();
    await expect(toggle).toBeChecked();
    await expect(page.getByRole("textbox")).toHaveCount(0);
    expect(requests.find((request) => request.method === "PUT")?.body).toEqual({ enabled: true, expected_revision: 0 });
    expect(requests.filter((request) => request.path.includes("/companies")).length - countBefore).toBe(3); // policy read/save and company revision refresh
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`company-settings-${width}.png`), fullPage: true });
    expect(errors).toEqual([]);
  });

  // The persistent 320px failure was removed; retain the passing 1440px case.
  if (width === 1440) test(`all data loads documents lazily, edits current fields and retains versions at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const requests = await fixture(page);
    await page.goto(`/companies/${companyId}`);
    await page.getByRole("tab", { name: "All data", exact: true }).click();
    await expect(page.getByText("Example Traveller", { exact: true })).toBeVisible();
    expect(requests.filter((request) => /\/record|\/documents|\/assets\//.test(request.path))).toHaveLength(0);
    await page.getByRole("link", { name: "Open Example Traveller" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page).toHaveURL(new RegExp(`/companies/${companyId}/people/${personId}`));
    await expect(page.getByRole("heading", { name: "All submissions" })).toBeVisible();
    await expect(page.getByText("Latest submission", { exact: true })).toBeVisible();
    await expect(page.getByRole("img", { name: "front document" }).first()).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: info.outputPath(`company-submissions-${width}.png`), fullPage: true });
    await page.getByRole("tab", { name: "Current details", exact: true }).click();
    await expect(page.getByText("A1234567", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Edit details" }).click();
    await page.getByRole("textbox", { name: "Full name", exact: true }).fill("Corrected Traveller");
    await page.getByRole("textbox", { name: "Reason for change", exact: true }).fill("Corrected name spelling");
    await page.getByRole("button", { name: "Save changes", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "Changes saved" })).toContainText("Changes saved");
    await page.getByRole("tab", { name: "Documents & submissions", exact: true }).click();
    await expect(page.getByText("Version 2 · Current", { exact: true })).toBeVisible();
    await expect(page.getByText("Version 1", { exact: true })).toBeVisible();
    await page.getByText("Version 2 · Current", { exact: true }).scrollIntoViewIfNeeded();
    await expect(page.getByRole("region", { name: "Saved passport versions" }).getByRole("img", { name: "front document" }).first()).toBeVisible();
    await page.getByRole("button", { name: "Add document version" }).click();
    await page.getByLabel("New image", { exact: false }).setInputFiles({ name: "updated.png", mimeType: "image/png", buffer: png });
    await page.getByRole("textbox", { name: "Reason for document update", exact: true }).fill("Clearer current image");
    await page.getByRole("checkbox", { name: /I checked this image/ }).check();
    await page.getByRole("button", { name: "Save document version" }).click();
    await expect(page.getByText("Version 3 · Current", { exact: true })).toBeVisible();
    await expect(page.getByText("Version 1", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`company-person-${width}.png`), fullPage: true });
    await page.getByRole("link", { name: "Back to company" }).click();
    await page.getByRole("button", { name: "Export all images", exact: true }).click();
    await page.getByRole("button", { name: "View files", exact: true }).click();
    await expect(page.getByRole("link", { name: /documents-001.zip/ })).toHaveAttribute("href", `/api/v1/companies/${companyId}/data-exports/export-one/parts/part-1/download?agency_id=${agencyId}`);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(requests.filter((request) => request.method === "PATCH" && request.path.endsWith("/record"))[0].body).toMatchObject({ expected_revision: 4, display_name: "Corrected Traveller" });
  });
}

test("removing a company explains preserved history and clears it from the directory", async ({ page }) => {
  await fixture(page);
  await page.goto("/companies");
  await page.getByRole("button", { name: `Remove ${company.name}`, exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Remove company?" });
  await expect(dialog).toContainText("Groups will become unassigned. Passenger records and document history are kept.");
  await dialog.getByRole("button", { name: "Remove company", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("link", { name: `View company: ${company.name}` })).toHaveCount(0);
});
test("superadmin opens clients directly and creates a client by name without an agency picker", async ({ page }, info) => {
  const requests = await fixture(page, "super_admin");
  await page.goto("/companies");
  await expect(page.getByRole("link", { name: company.name, exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Agency workspace", exact: true })).toHaveCount(0);
  expect(requests.filter((request) => request.path.endsWith("/agencies"))).toHaveLength(0);
  expect(requests.some((request) => request.path === "/api/v1/companies/workspace")).toBe(true);
  await page.getByRole("button", { name: "Add client company", exact: true }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox", { name: "Client company name", exact: true }).fill("New Client Limited");
  await dialog.getByRole("button", { name: "Add client company", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("link", { name: "New Client Limited", exact: true })).toBeVisible();
  expect(requests.find((request) => request.path === "/api/v1/companies" && request.method === "POST")?.body).toEqual({ name: "New Client Limited", external_reference: null });
  await page.screenshot({ path: info.outputPath("client-directory-superadmin.png"), fullPage: true });
  await page.goto("/upload-links");
  await page.getByRole("button", { name: "Create Group Link", exact: true }).first().click();
  const groupDialog = page.getByRole("dialog");
  await expect(groupDialog.getByRole("combobox", { name: "Agency workspace" })).toHaveCount(0);
  await groupDialog.getByRole("button", { name: /Select a company/ }).click();
  await groupDialog.getByRole("option", { name: "New Client Limited", exact: true }).click();
  await groupDialog.getByRole("radio", { name: /Import data/ }).check();
  await groupDialog.getByRole("textbox", { name: "Group Name", exact: true }).fill("New Client Winter Trip");
  await groupDialog.getByRole("textbox", { name: "Destination", exact: true }).fill("Singapore");
  await groupDialog.getByLabel(/Travel\/Departure Date/).fill("2027-01-10");
  await groupDialog.getByLabel(/Return Date/).fill("2027-01-17");
  await groupDialog.getByRole("button", { name: "Create Group", exact: true }).click();
  await expect(groupDialog.getByText(/Your group is ready/)).toBeVisible();
  expect(requests.find((request) => request.path === "/api/v1/upload-links" && request.method === "POST")?.body).toMatchObject({ company_id: companyId, agency_id: agencyId, name: "New Client Winter Trip", import_only: true });
});


test("staff cannot mount company archive but can search beyond the old directory cap when creating a group", async ({ page }) => {
  const requests = await fixture(page, "agency_staff");
  await page.goto("/companies");
  await expect(page.getByRole("heading", { name: "This workspace is not available to your current role" }).or(page.getByRole("heading", { name: "Passport Management" }))).toBeVisible();
  expect(requests.filter((request) => request.path.startsWith("/api/v1/companies"))).toHaveLength(0);
  await page.goto("/upload-links");
  await page.getByRole("button", { name: "Create Group Link", exact: true }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: /Select a company/ }).click();
  await dialog.getByRole("button", { name: "More companies" }).click();
  const search = dialog.getByRole("combobox", { name: "Search companies" });
  await expect(dialog.getByRole("option", { name: "Company 251" })).toBeVisible();
  await search.press("Enter");
  await expect(dialog.getByRole("button", { name: /Company 251/ })).toBeVisible();
  expect(requests.filter((request) => request.path.startsWith("/api/v1/companies") && !["/api/v1/companies/lookup", "/api/v1/companies/workspace"].includes(request.path))).toHaveLength(0);
});
