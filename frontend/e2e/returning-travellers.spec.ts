import { expect, test, type Page, type Route } from "@playwright/test";
import type { ReturningMethod } from "../features/travellers/types";
import { DEFAULT_UPLOAD_CONFIGURATION } from "../features/passports/types/upload-configuration";
import { mockPublicContactOtp, verifyPublicContact } from "./support/public-contact-otp";

const token = "synthetic-returning-trip";
const group = {
  id: "group-returning", name: "Returning Japan Trip", token, agency_id: "agency-synthetic", status: "active",
  created_at: "2026-10-01T00:00:00Z", destination: "Japan", travel_date: "2026-12-01", return_date: "2026-12-08",
  departure_cities: [], custom_questions: [], custom_details: [], qualifier_relation_options: [],
  base_city_enabled: false, nearest_international_airport_enabled: false, staff_code_enabled: false,
  agent_employee_code_enabled: false, meal_preference_enabled: false, require_selfie: false,
  allow_files_from_device: true, ask_nearest_domestic_airport: false, relation_with_qualifier_enabled: false,
  designation_enabled: false, agency_dealership_name_enabled: false, deleted_at: null,
};
const history = {
  display_name: "Synthetic Traveller", contact_phone: "+919999999999",
  passport: { id: "passport-a", number: "A1234567", issuing_country: "IND", document_type: "P", date_of_birth: "1990-01-01", issue_date: "2020-01-01", expiry_date: "2030-01-01", revision: 2 },
  extracted_fields: { surname: "Traveller", given_names: "Synthetic", passport_number: "A1234567", date_of_birth: "1990-01-01", issuing_country: "IND", nationality: "IND", date_of_expiry: "2030-01-01" },
  documents: [{ id: "synthetic-front", label: "Passport front", content_type: "image/png", available: true }],
  suitability: { outcome: "review_required", reason_codes: ["DESTINATION_RULE_UNKNOWN"] },
  group_requirements: { custom_questions: [{ id: "meal", label: "Meal for this trip", enabled: true, required: true, options: ["Veg", "Jain"] }], custom_details: [], require_selfie: false, require_contact_phone: false, current_detail_fields: [{ key: "staff_code", label: "Staff code", required: true, options: [], type: "text" }] },
  missing_requirements: [], question_version: "current-v2", review_version: "review-v2", participation_revision: null,
};
const json = (route: Route, data: unknown, status = 200, headers?: Record<string, string>) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data), headers });
const claimCookie = "synthetic-claim-secret-0123456789abcdef";
const historyCookie = "synthetic-history-secret-0123456789abcdef";
function cookieHeader(name: string, value: string) { return { "set-cookie": `${name}=${value}; Path=/api/v1/returning; HttpOnly; SameSite=Strict; Max-Age=600` }; }
function syntheticPdf() {
  const stream = "BT /F1 18 Tf 30 110 Td (SYNTHETIC PASSPORT REVIEW) Tj ET";
  const objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 360 180] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`];
  let data = "%PDF-1.4\n";
  const offsets = [0];
  for (const [index, object] of objects.entries()) { offsets.push(Buffer.byteLength(data)); data += `${index + 1} 0 obj\n${object}\nendobj\n`; }
  const xref = Buffer.byteLength(data);
  data += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.slice(1).map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("")}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(data);
}
async function setup(page: Page, options: { enabled?: boolean; failProof?: boolean; replacement?: boolean; protectedPdf?: boolean } = {}) {
  const calls: Array<{ path: string; body: Record<string, unknown> }> = [];
  let method: ReturningMethod = "phone";
  let granted = false;
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const body = req.headers()["content-type"]?.includes("application/json") ? req.postDataJSON() ?? {} : {};
    calls.push({ path, body });
    if (path === `/api/v1/upload-links/token/${token}`) return json(route, options.replacement ? { ...group, upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, passport_live_scan: false, passport_upload_pages: ["front"], visa_photo_required: false, visa_photo_live_capture: false, visa_photo_upload: false } } : group);
    if (path.endsWith("/returning/capabilities")) return json(route, { enabled: options.enabled !== false, code_label: "Producer code" });
    if (path.endsWith("/returning/claims")) { method = body.method; return json(route, { stage: method === "phone" ? "contact" : "identify" }, 200, options.protectedPdf ? cookieHeader("pd_returning_claim", claimCookie) : undefined); }
    if (options.protectedPdf && path.includes("/returning/")) expect(await req.headerValue("cookie")).toContain(`pd_returning_claim=${claimCookie}`);
    if (path.endsWith("/returning/otp/request") || path.endsWith("/returning/contact/request")) return json(route, { expires_in_seconds: 600, resend_after_seconds: 30 });
    if (path.endsWith("/returning/otp/verify")) return json(route, { stage: "identify" });
    if (path.endsWith("/returning/candidates")) return json(route, { items: [{ handle: "opaque-one", label: "T********", passport_hint: "••67" }, { handle: "opaque-two", label: "S*****", passport_hint: "••91" }], narrowing_required: false });
    if (path.endsWith("/returning/candidate")) return json(route, { stage: "passport" });
    if (path.endsWith("/returning/passport")) {
      if (options.failProof) return json(route, { detail: { code: "UNAVAILABLE", message: "The supplied information could not be verified." } }, 403);
      return json(route, method === "passport" ? { stage: "challenge", questions: ["date_of_birth"], can_change_question: true, available_questions: ["date_of_birth", "expiry_date"] } : { stage: "confirm" });
    }
    if (path.endsWith("/returning/challenge/change")) return json(route, { stage: "challenge", questions: [body.field], can_change_question: false });
    if (path.endsWith("/returning/challenge")) return json(route, { stage: "confirm" });
    if (path.endsWith("/returning/confirm")) { granted = true; return json(route, { stage: "review" }, 200, options.protectedPdf ? cookieHeader("pd_returning_history", historyCookie) : undefined); }
    if (path.endsWith("/returning/history")) { expect(granted).toBe(true); if (options.protectedPdf) expect(await req.headerValue("cookie")).toContain(`pd_returning_history=${historyCookie}`); return json(route, options.protectedPdf ? { ...history, documents: [{ ...history.documents[0], content_type: "application/pdf" }] } : history); }
    if (path.includes("/returning/documents/")) {
      expect(granted).toBe(true);
      if (options.protectedPdf) { expect(await req.headerValue("cookie")).toContain(`pd_returning_history=${historyCookie}`); return route.fulfill({ contentType: "application/pdf", body: syntheticPdf(), headers: { "cache-control": "private, no-store", "x-content-type-options": "nosniff" } }); }
      return route.fulfill({ contentType: "image/png", body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jPRkAAAAASUVORK5CYII=", "base64") });
    }
    if (path.endsWith("/returning/complete")) { expect(granted).toBe(true); return json(route, { status: "submitted", participation_id: "synthetic-participation" }); }
    if (path.endsWith("/returning/contact/verify")) return json(route, { stage: "review" });
    return json(route, { detail: "Unexpected synthetic request blocked" }, 403);
  });
  return calls;
}

test("protected PDF delivery uses path-scoped httpOnly cookies without CSP violations", async ({ page }, info) => {
  await setup(page, { protectedPdf: true });
  const violations: string[] = [];
  page.on("console", (message) => { if (/Content Security Policy|violat.*policy|refused to (frame|load)/i.test(message.text())) violations.push(message.text()); });
  await page.goto(`/upload/${token}`);
  await page.getByRole("button", { name: "Passport number", exact: true }).click();
  await passport(page); await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByLabel("Date of birth", { exact: false }).first().fill("01/01/1990");
  await page.getByRole("button", { name: "Verify passport details" }).click();
  await page.getByRole("checkbox", { name: /permission to view/ }).check();
  await page.getByRole("button", { name: "Review saved details" }).click();
  await page.getByRole("button", { name: /Passport front · Open preview/ }).click();
  await expect(page.locator('iframe[title="Passport front"]')).toBeVisible();
  await expect(page.getByRole("button", { name: /Passport front · Viewed/ })).toHaveCount(0);
  await page.getByRole("button", { name: "I can see and have reviewed this PDF" }).click();
  await expect(page.getByRole("button", { name: /Passport front · Viewed/ })).toBeVisible();
  await page.screenshot({ path: info.outputPath("protected-pdf-review.png"), fullPage: true });
  expect(violations).toEqual([]);
  expect(await page.evaluate(() => document.cookie)).not.toContain("pd_returning");
  const scoped = await page.context().cookies(new URL("/api/v1/returning/history", page.url()).href);
  expect(scoped.filter((cookie) => cookie.name.startsWith("pd_returning"))).toHaveLength(2);
  expect(scoped.filter((cookie) => cookie.name.startsWith("pd_returning")).every((cookie) => cookie.httpOnly && cookie.path === "/api/v1/returning" && cookie.sameSite === "Strict")).toBe(true);
  expect((await page.context().cookies(page.url())).some((cookie) => cookie.name.startsWith("pd_returning"))).toBe(false);
});
async function passport(page: Page) {
  await page.getByLabel("Full passport number", { exact: false }).fill("A1234567");
  await page.getByRole("combobox", { name: /Issuing country/ }).selectOption("IND");
}

for (const width of [320, 1440]) for (const method of ["phone", "passport", "code"] as const) {
  test(`${method} returning proof and current trip review at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const calls = await setup(page);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`/upload/${token}`);
    await page.getByRole("button", { name: method === "phone" ? "WhatsApp OTP" : method === "passport" ? "Passport number" : "Producer code", exact: true }).click();
    if (method === "phone") await page.getByLabel("WhatsApp number", { exact: false }).fill("9999999999");
    if (method === "passport") await passport(page);
    if (method === "code") await page.getByLabel("Producer code", { exact: false }).fill("00019");
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    if (method === "phone") {
      await page.getByRole("button", { name: "Send WhatsApp code" }).click();
      await page.getByLabel("WhatsApp verification code", { exact: false }).fill("123456");
      await page.getByRole("button", { name: "Verify code", exact: true }).click();
      await expect(page.getByRole("button", { name: /T\*+/ })).toBeVisible();
      expect(calls.filter((call) => call.path.endsWith("/history"))).toHaveLength(0);
      await page.getByRole("button", { name: /T\*+/ }).click();
    }
    if (method !== "passport") { await passport(page); await page.getByRole("button", { name: "Check passport" }).click(); }
    else {
      await page.getByLabel("Date of birth", { exact: false }).first().fill("01/01/1990");
      await page.getByRole("button", { name: "Verify passport details" }).click();
    }
    expect(calls.filter((call) => call.path.endsWith("/history"))).toHaveLength(0);
    await page.getByRole("checkbox", { name: /permission to view/ }).check();
    await page.getByRole("button", { name: "Review saved details" }).click();
    await expect(page.getByRole("heading", { name: "Review your saved passport" })).toBeVisible();
    expect(calls.filter((call) => call.path.includes("/documents/"))).toHaveLength(0);
    expect(calls.filter((call) => call.path.includes("/otp/"))).toHaveLength(method === "phone" ? 2 : 0);
    await page.getByRole("button", { name: /Passport front · Open preview/ }).click();
    await expect(page.getByRole("button", { name: /Passport front · Viewed/ })).toBeVisible();
    await page.getByRole("textbox", { name: /Staff code/ }).fill("0009");
    await page.getByRole("combobox", { name: /Meal for this trip/ }).selectOption("Jain");
    await page.getByRole("checkbox", { name: /reviewed the images/ }).check();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`returning-${method}-${width}.png`), fullPage: true });
    await page.getByRole("button", { name: "Submit this trip’s information" }).click();
    await expect(page.getByRole("heading", { name: "Trip information submitted" })).toBeVisible();
    expect(calls.find((call) => call.path.endsWith("/complete"))?.body).toMatchObject({ current_details: { staff_code: "0009" }, custom_answers: { meal: "Jain" }, question_version: "current-v2" });
    const storage = await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }));
    expect(storage).not.toContain("A1234567");
    expect(errors).toEqual([]);
  });
}

test("failed proof keeps history inaccessible and returns to fresh collection", async ({ page }) => {
  const calls = await setup(page, { failProof: true });
  await page.goto(`/upload/${token}`);
  await page.getByRole("button", { name: "Passport number", exact: true }).click();
  await passport(page);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "could not be verified" })).toContainText("could not be verified");
  expect(calls.filter((call) => call.path.endsWith("/history"))).toHaveLength(0);
  await page.getByRole("button", { name: "New traveller / Upload current documents" }).click();
  await expect(page.getByRole("heading", { name: "Travelled with us before?" })).toBeVisible();
});

test("unavailable reuse capabilities leave fresh collection available", async ({ page }) => {
  await setup(page, { enabled: false });
  await page.goto(`/upload/${token}`);
  await expect(page.getByText(group.name).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "WhatsApp OTP", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Single Submit travel details/ })).toBeVisible();
});

test("explicit renewal links the new single upload after submission without automatically promoting it", async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await setup(page, { replacement: true });
  await mockPublicContactOtp(page);
  const replacementCalls: Array<{ body: Record<string, unknown>; session: string | undefined }> = [];
  let uploadSession: string | undefined;
  let uploads = 0;
  const submitted = {
    id: "replacement-submission", group_id: group.id, agency_id: group.agency_id,
    client_name: "Synthetic Traveller", client_email: null, client_phone: null,
    status: "ready_for_client_review", extraction_status: "ready_for_review", extraction_revision: 6,
    image_s3_key: "synthetic-new-front", passport_back_s3_key: null, passport_photo_s3_key: null,
    created_at: "2026-10-13T00:00:00Z", updated_at: "2026-10-13T00:00:00Z",
    custom_answers: [], custom_detail_answers: [], error_message: null, confirmed_fields: null,
    extracted_fields: { surname: "TRAVELLER", given_names: "SYNTHETIC", passport_number: "B1234567", nationality: "IND", date_of_birth: "1990-01-01", date_of_issue: "2026-01-01", date_of_expiry: "2036-01-01", place_of_issue: "DELHI", sex: "M", ai_verification: { available: true, status: "verified", provider_status: "ok" } },
  };
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (path.includes("/prepare-file") || path.includes("/image/")) return route.fulfill({ contentType: "image/jpeg", body: imageBytes });
    if (path === `/api/v1/passports/upload/${token}`) {
      if (req.method() === "PUT") return json(route, { submission_id: null });
      uploads++; uploadSession = req.headers()["x-upload-session-id"]; return json(route, submitted);
    }
    if (path.endsWith("/replacement-submission/status")) return json(route, submitted);
    if (path.endsWith("/replacement-submission/client-submit")) return json(route, { ...submitted, status: "needs_review", ...req.postDataJSON() });
    if (path.endsWith("/returning/replacement-candidate")) {
      replacementCalls.push({ body: req.postDataJSON(), session: req.headers()["x-upload-session-id"] });
      return json(route, { status: "candidate_pending_review", match_case_id: "synthetic-case" });
    }
    if (path.endsWith("/telemetry")) return json(route, {});
    return route.fallback();
  });
  await page.goto(`/upload/${token}`);
  const imageBytes = Buffer.from(await page.evaluate(() => {
    const canvas = document.createElement("canvas"); canvas.width = 1200; canvas.height = 800;
    const context = canvas.getContext("2d")!; context.fillStyle = "#e2e8f0"; context.fillRect(0, 0, 1200, 800);
    context.fillStyle = "#0f172a"; context.font = "48px sans-serif"; context.fillText("SYNTHETIC TEST DOCUMENT", 80, 120);
    return canvas.toDataURL("image/jpeg", 0.85).split(",")[1];
  }), "base64");
  await page.getByRole("button", { name: "Passport number", exact: true }).click();
  await passport(page); await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByLabel("Date of birth", { exact: false }).first().fill("01/01/1990");
  await page.getByRole("button", { name: "Verify passport details" }).click();
  await page.getByRole("checkbox", { name: /permission to view/ }).check();
  await page.getByRole("button", { name: "Review saved details" }).click();
  await page.getByRole("button", { name: "Upload updated passport" }).click();
  await page.getByRole("radio", { name: "A renewed or replacement passport" }).check();
  await page.getByRole("button", { name: "Continue to updated document" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Updating the passport for Synthetic Traveller" })).toBeVisible();
  await page.getByRole("button", { name: "Upload passport images" }).click();
  await page.getByLabel("Upload Personal Details Page", { exact: true }).setInputFiles({ name: "synthetic-renewal.jpg", mimeType: "image/jpeg", buffer: imageBytes });
  await page.getByRole("button", { name: "Save passport pages and continue" }).click();
  await verifyPublicContact(page);
  await expect(page.getByRole("heading", { name: "Verify Passport Details" })).toBeVisible();
  await page.getByRole("button", { name: "Submit Verified Details", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Updated document submitted" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("awaiting staff review");
  expect(uploads).toBe(1);
  expect(replacementCalls).toHaveLength(1);
  expect(replacementCalls[0]).toMatchObject({ body: { source_submission_id: submitted.id, expected_extraction_revision: 6, review_version: "review-v2", change_kind: "renewal" }, session: uploadSession });
  expect(uploadSession).toBeTruthy();
  expect(await page.evaluate(() => JSON.stringify({ ...sessionStorage }))).not.toContain("review-v2");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("renewal-pending-review-320.png"), fullPage: true });
});
