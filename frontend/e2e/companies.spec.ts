import { expect, test, type Page, type Route } from "@playwright/test";
import type { Company, CompanyReference } from "../features/companies/types";

const agencyId = "11111111-1111-4111-8111-111111111111";
const companyId = "22222222-2222-4222-8222-222222222222";
const company: Company = { id: companyId, name: "Enterprise Travel Client", status: "active", external_reference: "00017", revision: 3, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z" };
const user = { id: "33333333-3333-4333-8333-333333333333", agency_id: agencyId, email: "company-admin@example.test", full_name: "Company Admin", role: "agency_admin", is_active: true, created_at: company.created_at, updated_at: company.updated_at, last_login_at: null, capabilities: [] };
const respond = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function fixture(page: Page, role = "agency_admin") {
  let saved = { ...company };
  let policy = { company_id: companyId, enabled: false, revision: 0, retention_mode: "until_withdrawn", retention_days: null, purpose_version: null, notice_version: null, processing_basis: null, configured_at: null };
  const requests: Array<{ path: string; method: string; body: unknown }> = [];
  await page.context().addCookies([{ name: "access_token", value: "synthetic-companies-test", domain: "127.0.0.1", path: "/", httpOnly: true }]);
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    requests.push({ path, method: req.method(), body: req.postDataJSON() });
    if (path === "/api/v1/auth/me") return respond(route, { ...user, role });
    if (path === "/api/v1/auth/refresh") return respond(route, { status: "authenticated", user: { ...user, role }, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (path === "/api/v1/notifications/feed") return respond(route, { items: [], unread_count: 0, next_cursor: null });
    if (path === "/api/v1/gc-app/admin/agencies") return respond(route, { items: [{ id: agencyId, name: "Synthetic agency" }], total: 1, offset: 0, limit: 25 });
    if (path === "/api/v1/companies/lookup") {
      const option: CompanyReference = url.searchParams.has("cursor") ? { id: companyId, name: "Company 251", status: "active" } : saved;
      return respond(route, { items: [option], next_cursor: url.searchParams.has("cursor") ? null : "opaque-page-2", has_more: !url.searchParams.has("cursor") });
    }
    if (path.startsWith("/api/v1/companies")) {
      expect(url.searchParams.get("agency_id")).toBe(agencyId);
      if (path.endsWith("/reuse-policy")) {
        if (req.method() === "PUT") policy = { ...policy, ...req.postDataJSON(), revision: policy.revision + 1 };
        return respond(route, policy);
      }
      if (path.endsWith("/reuse-config")) return respond(route, { group_id: "group-1", company_id: companyId, group_revision: 2, revision: 0, enabled: false, roster_mode: "closed", individual_identifier_type: null, identifier_required: false });
      if (path.endsWith("/enrollment-sources")) return respond(route, { items: [{ id: "source-submission", display_name: "Accepted Person", status: "staff_approved", extraction_revision: 7 }], next_cursor: null, expected_group_revision: 3 });
      if (path.endsWith("/travellers/enroll")) return respond(route, { traveller_id: "person", passport_id: "passport", document_revision_id: "revision", copies_pending: 2 }, 202);
      if (path === `/api/v1/companies/${companyId}/summary`) return respond(route, { active_groups: 1, closed_groups: 1, archived_groups: 1, total_groups: 3, unique_travellers: null, trip_participations: null, unresolved_historical_records: 700, identity_totals_partial: true });
      if (path === `/api/v1/companies/${companyId}/groups`) return respond(route, { items: [{ id: "group-1", name: "Japan Autumn", destination: "Japan", travel_date: "2026-11-01", return_date: "2026-11-08", status: "archived", import_only: true, submission_count: 700 }], next_cursor: null, has_more: false });
      if (path === `/api/v1/companies/${companyId}/travellers`) return respond(route, { items: [{ id: "person-1", display_name: "Example Traveller", participation_count: 2, last_trip_date: "2026-11-01", status: "active" }], next_cursor: null });
      if (path.endsWith("/history")) return respond(route, { items: [{ id: "membership-1", group_id: "group-1", group_name: "Japan Autumn", travel_date: "2026-11-01", lifecycle: "archived", participation_status: "accepted", document_revision: 2 }], next_cursor: null });
      if (path === `/api/v1/companies/${companyId}`) {
        if (req.method() === "PATCH") {
          const body = req.postDataJSON();
          expect(body.expected_revision).toBe(saved.revision);
          saved = { ...saved, ...body, revision: saved.revision + 1 };
        }
        if (req.method() === "DELETE") return respond(route, { detail: "This company has retained groups and cannot be deleted." }, 409);
        return respond(route, saved);
      }
      if (req.method() === "POST") { saved = { ...saved, ...req.postDataJSON(), revision: 1 }; return respond(route, saved, 201); }
      return respond(route, { items: [saved], next_cursor: null, has_more: false });
    }
    if (req.method() === "GET") return respond(route, []);
    return respond(route, { detail: "Unexpected test mutation blocked" }, 403);
  });
  return requests;
}

test("reuse setup is explicit, lazily loaded and mobile accessible", async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 900 });
  const requests = await fixture(page);
  await page.goto(`/companies/${companyId}`);
  await expect(page.getByRole("heading", { name: company.name })).toBeVisible();
  expect(requests.filter((req) => /reuse-policy|reuse-config/.test(req.path))).toHaveLength(0);
  await page.getByRole("button", { name: "Configure reuse" }).click();
  await page.getByRole("checkbox", { name: /Enable returning/ }).check();
  await expect(page.getByRole("button", { name: "Save reuse settings" })).toBeDisabled();
  await page.getByRole("textbox", { name: "Documented purpose version", exact: false }).fill("approved-travel-v2");
  await page.getByRole("textbox", { name: "Privacy notice version", exact: false }).fill("approved-notice-v3");
  await page.getByRole("textbox", { name: "Documented processing basis", exact: false }).fill("Approved traveller consent");
  await page.getByRole("button", { name: "Save reuse settings" }).click();
  await expect.poll(() => requests.filter((req) => req.method === "PUT")).toHaveLength(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "Reuse settings", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Group reuse settings" });
  await expect(dialog.getByRole("checkbox", { name: /Enable verified/ })).toBeDisabled();
  await expect(dialog.getByText("Reuse can be enabled for active collection groups.")).toBeVisible();
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("reuse-config-320.png"), fullPage: true });
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("button", { name: "Enroll accepted traveller", exact: true }).click();
  const enrollment = page.getByRole("dialog", { name: "Enable a traveller’s future reuse" });
  await enrollment.getByRole("radio", { name: /Accepted Person/ }).check();
  const popupPromise = page.waitForEvent("popup");
  await enrollment.getByRole("link", { name: "Review this saved submission" }).click();
  const popup = await popupPromise; await popup.close();
  await enrollment.getByRole("combobox", { name: "Reviewed issuing country" }).selectOption("IND");
  await enrollment.getByRole("textbox", { name: "Reviewed document type", exact: false }).fill("P");
  await enrollment.getByRole("checkbox", { name: /inspected the source passport/ }).check();
  await enrollment.getByRole("textbox", { name: "Recorded permission evidence reference", exact: false }).fill("signed-permission-reference-442");
  await enrollment.getByRole("checkbox", { name: /checked the accepted document/ }).check();
  expect(await enrollment.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("traveller-enrollment-320.png"), fullPage: true });
  await enrollment.getByRole("button", { name: "Enroll accepted traveller", exact: true }).click();
  await expect(enrollment.getByText(/2 protected document copies/)).toBeVisible();
  const enrolled = requests.find((req) => req.path.endsWith("/travellers/enroll"));
  expect(enrolled?.body).toMatchObject({ source_submission_id: "source-submission", expected_extraction_revision: 7, expected_group_revision: 3, permission_evidence_reference: "signed-permission-reference-442", change_kind: "initial" });
});

test("superadmin explicitly selects a bounded agency workspace", async ({ page }) => {
  const requests = await fixture(page, "super_admin");
  await page.goto("/companies");
  await expect(page.getByText("Select an agency workspace to continue.")).toBeVisible();
  expect(requests.filter((request) => request.path === "/api/v1/companies")).toHaveLength(0);
  await page.getByRole("combobox", { name: "Agency workspace", exact: true }).selectOption(agencyId);
  await expect(page.getByRole("link", { name: company.name })).toBeVisible();
  expect(requests.filter((request) => request.path.endsWith("/agencies"))).toHaveLength(1);
});

test("matching preview is lazy, bounded and records only a reviewed roster association at 320px", async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await fixture(page);
  let queued = false;
  let reads = 0;
  const decisions: Record<string, unknown>[] = [];
  const travellerId = "33333333-3333-4333-8333-333333333333";
  await page.route("**/api/v1/companies/**/travellers/**", async (route) => {
    const request = route.request(); const url = new URL(request.url());
    if (url.pathname.endsWith("/matching-preview")) {
      if (request.method() === "POST") { queued = true; return respond(route, { job_id: "job-one", status: "queued" }, 202); }
      reads++;
      expect(url.searchParams.get("page_size")).toBe("25");
      return respond(route, { items: [{ id: "match-one", source_kind: "passport_submission", source_row_key: "44444444-4444-4444-8444-444444444444", status: "provisional", reason_code: "exact_passport", traveller_id: travellerId, revision: 3 }], next_cursor: null, counts: { provisional: 1 }, latest_job_status: queued ? "queued" : null, processed_count: 1, expected_group_revision: 9 });
    }
    if (url.pathname.endsWith("/matches/match-one/resolve")) { decisions.push(request.postDataJSON()); return respond(route, { participation_id: "pending-person", status: "pending" }); }
    return route.fallback();
  });
  await page.goto(`/companies/${companyId}`);
  await expect(page.getByRole("heading", { name: company.name })).toBeVisible();
  expect(reads).toBe(0);
  await page.getByRole("button", { name: "Review matches", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Review traveller matches" });
  await dialog.getByRole("button", { name: "Run matching preview" }).click();
  await expect(dialog.getByText(/Latest matching job: queued/)).toBeVisible();
  await dialog.getByRole("button", { name: "Review association" }).click();
  await expect(dialog.getByRole("radio", { name: /Use the proposed traveller/ })).not.toBeChecked();
  await dialog.getByRole("radio", { name: /Use the proposed traveller/ }).check();
  await dialog.getByLabel(/Evidence and decision reason/).fill("Reviewed source records and confirmed the exact traveller profile.");
  await dialog.getByRole("checkbox", { name: /reviewed the source evidence/ }).check();
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("matching-review-320.png"), fullPage: true });
  await dialog.getByRole("button", { name: "Record roster decision" }).click();
  await expect(dialog.getByText("Roster decision saved")).toBeVisible();
  await expect(dialog.getByText(/Membership state:/)).toHaveText("Membership state: pending");
  expect(decisions).toHaveLength(1);
  expect(decisions[0]).toMatchObject({ traveller_id: travellerId, expected_revision: 3, expected_group_revision: 9, evidence_reviewed: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("review tasks and masked passport status controls load on demand at 320px", async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await fixture(page);
  const calls: Array<{ path: string; method: string; body: unknown }> = [];
  let resolved = false;
  let blocked = false;
  const task = { id: "task-one", group_id: "group-1", traveller_id: "person-1", source_submission_id: "source-one", old_document_revision_id: "11111111-1111-4111-8111-111111111111", new_document_revision_id: "22222222-2222-4222-8222-222222222222", status: "pending", reason_code: "document_renewed", revision: 2, expected_participation_revision: 3, current_participation_revision: 5, created_at: "2026-10-13T12:00:00Z", resolved_at: null, resolution_reason: null };
  await page.route("**/api/v1/companies/**", async (route) => {
    const req = route.request(); const path = new URL(req.url()).pathname;
    if (path.includes("/review-tasks") || /\/passports(?:\/|$)/.test(path)) {
      calls.push({ path, method: req.method(), body: req.postDataJSON() });
      if (path.endsWith("/review-tasks/task-one")) { resolved = true; return respond(route, { ...task, status: "resolved", revision: 3 }); }
      if (path.endsWith("/review-tasks")) return respond(route, { items: resolved ? [] : [task], next_cursor: null, has_more: false });
      if (path.endsWith("/passports/passport-one")) { blocked = true; return route.fulfill({ status: 204 }); }
      return respond(route, { items: [{ id: "passport-one", passport_hint: "********67", issuing_country: "IND", document_type: "P", status: blocked ? "lost" : "active", is_default: true, revision: blocked ? 5 : 4, issue_date: "2020-01-01", expiry_date: "2030-01-01" }], profile_revision: blocked ? 10 : 9, limit_reached: false });
    }
    return route.fallback();
  });
  await page.goto(`/companies/${companyId}`);
  await expect(page.getByRole("heading", { name: company.name })).toBeVisible();
  expect(calls).toHaveLength(0);
  await page.getByRole("tab", { name: "Review tasks" }).click();
  await page.getByRole("button", { name: "Record review outcome" }).click();
  const review = page.getByRole("dialog", { name: "Record document review" });
  await review.getByLabel(/Review note/).fill("Checked the ticket, visa and manifest for this trip.");
  await review.getByRole("checkbox", { name: /reviewed the affected trip/ }).check();
  expect(await review.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("review-task-320.png"), fullPage: true });
  await review.getByRole("button", { name: "Save review outcome" }).click();
  await expect(review).toBeHidden();
  expect(calls.find((call) => call.method === "PATCH")?.body).toMatchObject({ expected_revision: 2, expected_participation_revision: 5 });
  await page.getByRole("tab", { name: "Travellers & history" }).click();
  await page.getByRole("button", { name: "View history" }).click();
  expect(calls.filter((call) => call.path.endsWith("/passports"))).toHaveLength(0);
  await page.getByRole("button", { name: "Manage passports" }).click();
  const inventory = page.getByRole("dialog", { name: "Manage traveller passports" });
  await inventory.getByRole("button", { name: /Change status/ }).click();
  await expect(inventory.getByRole("button", { name: "Confirm passport status" })).toBeDisabled();
  await inventory.getByRole("checkbox", { name: /verified this passport/ }).check();
  expect(await inventory.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("passport-status-320.png"), fullPage: true });
  await inventory.getByRole("button", { name: "Confirm passport status" }).click();
  await expect(inventory.getByRole("status")).toContainText("Passport status updated");
  expect(calls.find((call) => call.path.endsWith("/passports/passport-one"))?.body).toEqual({ status: "lost", expected_profile_revision: 9, expected_passport_revision: 4 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

for (const width of [320, 1440]) {
  test(`company directory and lazy history remain usable at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const requests = await fixture(page);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/companies");
    await expect(page.getByRole("heading", { name: "Companies / Clients", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: company.name })).toBeVisible();
    await page.getByRole("button", { name: `Edit ${company.name}` }).click();
    const dialog = page.getByRole("dialog", { name: "Edit company / client" });
    await dialog.getByRole("textbox", { name: "Company name" }).fill("Renamed Enterprise Client");
    await dialog.getByRole("button", { name: "Save changes" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("link", { name: "Renamed Enterprise Client" })).toBeVisible();
    await page.getByRole("button", { name: "Deactivate", exact: true }).click();
    await page.getByRole("button", { name: "Confirm status change" }).click();
    await expect(page.getByRole("region", { name: "Company directory" }).getByRole("listitem").getByText("Inactive", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Delete Renamed Enterprise Client" }).click();
    await page.getByRole("button", { name: "Delete company", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: "retained groups" })).toBeVisible();
    await page.getByRole("link", { name: "Renamed Enterprise Client" }).click();
    await expect(page.getByRole("heading", { name: "Renamed Enterprise Client" })).toBeVisible();
    await expect(page.getByText("Unique travellers · partial", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Japan Autumn" })).toBeVisible();
    expect(requests.filter((request) => request.path.endsWith("/history"))).toHaveLength(0);
    await page.getByRole("tab", { name: "Travellers & history" }).click();
    await page.getByRole("button", { name: "View history" }).click();
    await expect(page.getByText("Document revision used: 2")).toBeVisible();
    expect(requests.filter((request) => request.path.endsWith("/history"))).toHaveLength(1);
    expect(requests.filter((request) => /image|download|preview/.test(request.path))).toHaveLength(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const main = page.locator("#main-content");
    expect(await main.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`company-history-${width}.png`), fullPage: true });
    expect(errors).toEqual([]);
  });
}

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
  expect(requests.filter((request) => request.path.startsWith("/api/v1/companies") && request.path !== "/api/v1/companies/lookup")).toHaveLength(0);
});
