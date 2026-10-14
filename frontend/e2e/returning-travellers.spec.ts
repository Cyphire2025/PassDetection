import { expect, test, type Page, type Route } from "@playwright/test";
import type { ReturningMethod } from "../features/travellers/types";
import { DEFAULT_UPLOAD_CONFIGURATION } from "../features/passports/types/upload-configuration";
import type { FreshCollection } from "../features/upload/api/fresh-draft.api";

const token = "synthetic-returning-trip";
const group = {
  id: "group-returning", name: "Returning Japan Trip", token, agency_id: "agency-synthetic", status: "active",
  created_at: "2026-10-01T00:00:00Z", destination: "Japan", travel_date: "2026-12-01", return_date: "2026-12-08",
  departure_cities: [], custom_questions: [], custom_details: [], qualifier_relation_options: [],
  base_city_enabled: false, nearest_international_airport_enabled: false, staff_code_enabled: false,
  agent_employee_code_enabled: false, meal_preference_enabled: false, require_selfie: false,
  allow_files_from_device: true, ask_nearest_domestic_airport: false, relation_with_qualifier_enabled: false,
  designation_enabled: false, agency_dealership_name_enabled: false, deleted_at: null,
  upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, passport_live_scan: false, passport_upload_pages: ["front", "back"], visa_photo_required: false, visa_photo_live_capture: false, visa_photo_upload: false },
};
const history = {
  display_name: "Synthetic Traveller", contact_phone: "+919999999999",
  passport: { id: "passport-a", number: "A1234567", issuing_country: "IND", document_type: "P", date_of_birth: "1990-01-01", issue_date: "2020-01-01", expiry_date: "2030-01-01", revision: 2 },
  extracted_fields: { surname: "Traveller", given_names: "Synthetic", passport_number: "A1234567", date_of_birth: "1990-01-01", date_of_issue: "2020-01-01", nationality: "Indian", date_of_expiry: "2030-01-01", place_of_issue: "Delhi", sex: "M" },
  documents: [{ id: "synthetic-front", label: "Front", content_type: "image/png", available: true }, { id: "synthetic-back", label: "Back", content_type: "image/png", available: true }],
  suitability: { outcome: "review_required", reason_codes: ["DESTINATION_RULE_UNKNOWN"] },
  group_requirements: { custom_questions: [{ id: "meal", label: "Meal for this trip", enabled: true, required: true, options: ["Veg", "Jain"] }], custom_details: [], require_selfie: false, require_contact_phone: false, current_detail_fields: [{ key: "staff_code", label: "Staff code", required: true, options: [], type: "text" }] },
  missing_requirements: [], question_version: "current-v2", review_version: "review-v2", participation_revision: null,
};
const json = (route: Route, data: unknown, status = 200, headers?: Record<string, string>) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data), headers });
const imageBytes = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jPRkAAAAASUVORK5CYII=", "base64");
function cookieHeader(name: string) { return { "set-cookie": name + "=synthetic-private-capability-0123456789; Path=/api/v1/returning; HttpOnly; SameSite=Strict; Max-Age=600" }; }
function syntheticPdf() {
  const stream = "BT /F1 18 Tf 30 110 Td (SYNTHETIC PASSPORT REVIEW) Tj ET";
  const objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 360 180] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", "<< /Length " + Buffer.byteLength(stream) + " >>\nstream\n" + stream + "\nendstream"];
  let data = "%PDF-1.4\n"; const offsets = [0];
  for (const [index, object] of objects.entries()) { offsets.push(Buffer.byteLength(data)); data += (index + 1) + " 0 obj\n" + object + "\nendobj\n"; }
  const xref = Buffer.byteLength(data);
  data += "xref\n0 " + (objects.length + 1) + "\n0000000000 65535 f \n" + offsets.slice(1).map((offset) => String(offset).padStart(10, "0") + " 00000 n \n").join("") + "trailer\n<< /Size " + (objects.length + 1) + " /Root 1 0 R >>\nstartxref\n" + xref + "\n%%EOF\n";
  return Buffer.from(data);
}
async function setup(page: Page, options: { enabled?: boolean; failProof?: boolean; protectedPdf?: boolean; collection?: boolean; cameraOnly?: boolean } = {}) {
  const calls: Array<{ path: string; method: string; body: Record<string, unknown> }> = [];
  let method: ReturningMethod = "phone"; let granted = false;
  let draft = { id: "draft-synthetic", revision: 1, expires_at: new Date(Date.now() + 86400000).toISOString(), status: "active", passport_fields: history.extracted_fields, current_details: {} as Record<string, string>, custom_answers: {} as Record<string, string>, custom_detail_answers: {}, collection: null as FreshCollection | null, verified_phone: null, documents: [] as Array<{ id: string; side: string; state: string }>, extraction_status: "none", extracted_fields: {} };
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request(); const path = new URL(req.url()).pathname;
    const body = req.headers()["content-type"]?.includes("application/json") ? req.postDataJSON() ?? {} : {};
    calls.push({ path, method: req.method(), body });
    if (path.includes("/returning/draft") && !(path.endsWith("/draft") && req.method() === "POST")) expect(req.headers()["x-returning-draft-id"]).toBe(draft.id);
    if (path === "/api/v1/upload-links/token/" + token) return json(route, options.collection ? { ...group, require_selfie: true, relation_with_qualifier_enabled: true, qualifier_relation_options: [{ code: "spouse", label: "Spouse" }], upload_configuration: { ...group.upload_configuration, visa_photo_required: true, visa_photo_upload: true } } : options.cameraOnly ? { ...group, allow_files_from_device: false, upload_configuration: { ...group.upload_configuration, passport_live_scan: true } } : group);
    if (path.endsWith("/qualifier-selection")) { expect(req.headers()["x-upload-session-id"]).toBeTruthy(); return json(route, { selection_token: "current-trip-selection" }); }
    if (path.endsWith("/prepare-file")) { expect(req.headers()["x-upload-session-id"]).toBeTruthy(); return route.fulfill({ contentType: "image/jpeg", body: imageBytes }); }
    if (path.endsWith("/returning/capabilities")) return json(route, { enabled: options.enabled !== false, code_label: "Producer code" });
    if (path.endsWith("/returning/claims")) { method = body.method; return json(route, { stage: method === "phone" ? "contact" : "identify" }, 200, cookieHeader("pd_returning_claim")); }
    if (path.endsWith("/returning/otp/request")) return json(route, { expires_in_seconds: 600, resend_after_seconds: 30 });
    if (path.endsWith("/returning/otp/verify")) return json(route, { stage: "identify" });
    if (path.endsWith("/returning/candidates")) return json(route, { items: [{ handle: "opaque-one", label: "T********", passport_hint: "••67" }], narrowing_required: false });
    if (path.endsWith("/returning/candidate")) return json(route, { stage: "passport" });
    if (path.endsWith("/returning/passport")) return json(route, method === "passport" ? { stage: "challenge", questions: ["date_of_birth"], can_change_question: true, available_questions: ["date_of_birth", "expiry_date"] } : options.failProof ? { detail: { code: "UNAVAILABLE", message: "Details could not be verified" } } : { stage: "confirm" }, options.failProof && method !== "passport" ? 403 : 200);
    if (path.endsWith("/returning/challenge/change")) return json(route, { stage: "challenge", questions: [body.field], can_change_question: false });
    if (path.endsWith("/returning/challenge")) return json(route, options.failProof ? { detail: { code: "UNAVAILABLE", message: "Details could not be verified" } } : { stage: "confirm" }, options.failProof ? 403 : 200);
    if (path.endsWith("/returning/confirm")) { expect(body).toEqual({}); granted = true; return json(route, { stage: "review" }, 200, cookieHeader("pd_returning_history")); }
    if (path.endsWith("/returning/history")) {
      expect(new URL(req.url()).searchParams.get("group_token")).toBe(token);
      expect(granted).toBe(true); expect(await req.headerValue("cookie")).toContain("pd_returning_history=");
      return json(route, options.protectedPdf ? { ...history, documents: [{ ...history.documents[0], content_type: "application/pdf" }] } : options.collection ? { ...history, missing_requirements: ["visa_photo", "qualifier_relationship"] } : history);
    }
    if (path.endsWith("/returning/draft")) {
      expect(granted).toBe(true);
      if (req.method() === "PUT") draft = { ...draft, ...body, revision: draft.revision + 1 };
      if (req.method() === "POST" && draft.status === "active" && draft.documents.length) draft = { ...draft, revision: draft.revision + 1, documents: [], extraction_status: "none" };
      return json(route, draft, 200, cookieHeader("pd_returning_draft"));
    }
    if (path.endsWith("/returning/draft/activity")) return json(route, { images_present: draft.documents.length > 0, presence_recorded: true, heartbeat_after_seconds: 60 });
    if (path.endsWith("/returning/draft/discard-documents")) {
      if (draft.status === "active") draft = { ...draft, revision: draft.revision + 1, documents: [], extraction_status: "none" };
      return json(route, draft);
    }
    if (path.includes("/returning/draft/documents/") && req.method() === "POST") {
      expect(req.headers()["content-type"]).toContain("multipart/form-data; boundary=");
      const side = path.split("/").at(-1)!;
      draft = { ...draft, revision: draft.revision + 1, documents: [...draft.documents.filter((item) => item.side !== side), { id: "new-" + side, side, state: "ready" }], extraction_status: "succeeded",
        passport_fields: side === "front" ? { ...draft.passport_fields, passport_number: "B7654321", date_of_issue: "2026-01-01", date_of_expiry: "2036-01-01" } : draft.passport_fields };
      return json(route, draft);
    }
    if (path.includes("/returning/documents/") || path.includes("/returning/draft/documents/")) {
      expect(granted).toBe(true); expect(await req.headerValue("cookie")).toContain("pd_returning_history=");
      return route.fulfill({ contentType: options.protectedPdf ? "application/pdf" : "image/png", body: options.protectedPdf ? syntheticPdf() : imageBytes, headers: { "cache-control": "private, no-store", "x-content-type-options": "nosniff" } });
    }
    if (path.endsWith("/returning/draft/complete")) { expect(granted).toBe(true); expect(body.expected_revision).toBe(draft.revision); draft.status = "submitted"; return json(route, { status: "submitted", participation_id: "synthetic-participation", source_submission_id: "synthetic-source" }); }
    return json(route, { detail: "Unexpected synthetic request blocked" }, 403);
  });
  return { calls, currentDraft: () => draft };
}
async function begin(page: Page, method: ReturningMethod) {
  await page.goto("/upload/" + token);
  await page.getByRole("button", { name: /Travelled with us before/ }).click();
  await page.getByRole("button", { name: method === "phone" ? /WhatsApp OTP/ : method === "passport" ? /Passport number/ : /Agent \/ employee code/ }).click();
  if (method === "phone") {
    await page.getByLabel("WhatsApp number", { exact: false }).fill("9999999999");
    await page.getByRole("button", { name: "Send OTP", exact: true }).click();
    await page.getByLabel("Enter verification code", { exact: false }).fill("123456");
    await page.getByRole("button", { name: "Verify WhatsApp", exact: true }).click();
    await page.getByRole("button", { name: /T\*+/ }).click();
  } else if (method === "code") {
    await page.getByLabel("Producer code", { exact: false }).fill("00019");
    await page.getByRole("button", { name: "Continue", exact: true }).click();
  }
  await page.getByLabel("Full passport number", { exact: false }).fill("A1234567");
  await page.getByRole("button", { name: method === "passport" ? "Continue" : "Verify passport", exact: true }).click();
  if (method === "passport") {
    await page.getByLabel("Date of birth", { exact: false }).first().fill("01/01/1990");
    await page.getByRole("button", { name: "Verify and view passport" }).click();
  }
}
async function fillTrip(page: Page) {
  await page.getByLabel("Staff code", { exact: false }).fill("0009");
  await page.getByRole("combobox", { name: /Meal for this trip/ }).selectOption("Jain");
}
for (const width of [320, 1440]) for (const method of ["phone", "passport", "code"] as const) {
  test(method + " verification and inline draft review at " + width + "px", async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const { calls, currentDraft } = await setup(page); const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await begin(page, method);
    await expect(page.getByRole("heading", { name: "Ready for your next journey" })).toBeVisible();
    await expect(page.getByRole("img", { name: "Passport details page" })).toBeVisible();
    await page.getByRole("img", { name: "Passport address page" }).scrollIntoViewIfNeeded();
    await expect(page.getByRole("img", { name: "Passport address page" })).toBeVisible();
    await expect(page.getByText("Issuing country", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Confirm access", { exact: true })).toHaveCount(0);
    expect(calls.filter((call) => call.path.includes("/otp/"))).toHaveLength(method === "phone" ? 2 : 0);
    await fillTrip(page);
    expect(calls.filter((call) => call.path.endsWith("/complete"))).toHaveLength(0);
    await page.getByRole("checkbox", { name: /reviewed my passport/ }).check();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath("returning-" + method + "-" + width + ".png"), fullPage: true });
    await page.getByRole("button", { name: "Submit trip details" }).click();
    await expect(page.getByRole("heading", { name: "Your trip details are saved" })).toBeVisible();
    expect(currentDraft()).toMatchObject({ current_details: { staff_code: "0009" }, custom_answers: { meal: "Jain" } });
    const storage = await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }));
    expect(storage).not.toContain("A1234567"); expect(errors).toEqual([]);
  });
}
test("first page has only two choices and a saved draft resumes for one day", async ({ page }, info) => {
  const { calls } = await setup(page);
  await page.goto("/upload/" + token);
  await expect(page.getByRole("button", { name: /Travelled with us before/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /New traveller/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /WhatsApp OTP|Single|Family/ })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("portal-first-page.png"), fullPage: true });
  await begin(page, "passport"); await fillTrip(page);
  await expect.poll(() => calls.filter((call) => call.path.endsWith("/draft") && call.method === "PUT").length).toBeGreaterThan(0);
  await page.reload();
  await page.getByRole("button", { name: /Continue from where you left/ }).click();
  await expect(page.getByLabel("Staff code", { exact: false })).toHaveValue("0009");
  await expect(page.getByRole("combobox", { name: /Meal for this trip/ })).toHaveValue("Jain");
});
test("failed passport plus date proof highlights the new-traveller action without disclosing history", async ({ page }) => {
  const { calls } = await setup(page, { failProof: true });
  await begin(page, "passport");
  await expect(page.getByRole("alert").filter({ hasText: "couldn’t verify a saved record" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue as a new traveller" })).toBeFocused();
  expect(calls.filter((call) => call.path.endsWith("/history") || call.path.includes("/documents/"))).toHaveLength(0);
});
test("independent back/front replacement remains a draft and updates visible fields before submit", async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 900 });
  const { calls } = await setup(page); await begin(page, "passport");
  await page.getByRole("button", { name: "Upload updated passport" }).click();
  await expect(page.getByLabel("Upload address details page")).toBeEnabled();
  await page.getByLabel("Upload address details page").setInputFiles({ name: "back.png", mimeType: "image/png", buffer: imageBytes });
  await expect(page.getByRole("img", { name: "Passport address page" })).toBeVisible();
  await page.getByLabel("Upload personal details page").setInputFiles({ name: "front.png", mimeType: "image/png", buffer: imageBytes });
  await expect(page.getByLabel("Passport Number", { exact: true })).toHaveValue("B7654321");
  await fillTrip(page); await page.getByRole("checkbox", { name: /reviewed my passport/ }).check();
  expect(calls.filter((call) => call.path.endsWith("/complete") || (call.path.includes("/passports/upload/") && !call.path.endsWith("/prepare-file")) || call.path.endsWith("/client-submit"))).toHaveLength(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("draft-replacement-320.png"), fullPage: true });
  await page.getByRole("button", { name: "Submit trip details" }).click();
  await expect(page.getByRole("heading", { name: "Your trip details are saved" })).toBeVisible();
  expect(calls.filter((call) => call.path.endsWith("/draft/complete"))).toHaveLength(1);
});
test("inline protected PDF uses scoped HttpOnly cookies without CSP violations", async ({ page }) => {
  await setup(page, { protectedPdf: true }); const violations: string[] = [];
  page.on("console", (message) => { if (/Content Security Policy|violat.*policy|refused to (frame|load)/i.test(message.text())) violations.push(message.text()); });
  await begin(page, "passport");
  await expect(page.locator('iframe[title="Passport details page"]')).toBeVisible();
  expect(await page.evaluate(() => document.cookie)).not.toContain("pd_returning");
  const scoped = (await page.context().cookies(new URL("/api/v1/returning/history", page.url()).href)).filter((cookie) => cookie.name.startsWith("pd_returning"));
  expect(scoped).toHaveLength(3); expect(scoped.every((cookie) => cookie.httpOnly && cookie.path === "/api/v1/returning" && cookie.sameSite === "Strict")).toBe(true);
  expect(violations).toEqual([]);
});

test("camera-only replacement opens the scanner and never offers a file bypass", async ({ page }) => {
  await setup(page, { cameraOnly: true });
  await page.addInitScript(() => { Object.defineProperty(navigator.mediaDevices, "getUserMedia", { value: () => Promise.reject(new DOMException("Synthetic camera denied", "NotAllowedError")) }); });
  await begin(page, "passport");
  await page.getByRole("button", { name: "Upload updated passport" }).click();
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Use camera", exact: true }).nth(1)).toBeEnabled();
  await page.getByRole("button", { name: "Use camera", exact: true }).first().click();
  await expect(page.getByText("Camera access was blocked. Allow camera permission in your browser and try again.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Try Camera Again" })).toBeVisible();
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
});

test("relationship and details resume while the temporary photo must be selected again", async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 900 });
  const { calls, currentDraft } = await setup(page, { collection: true });
  await begin(page, "passport"); await fillTrip(page);
  await page.getByRole("checkbox", { name: /reviewed my passport/ }).check();
  await expect(page.getByRole("button", { name: "Submit trip details" })).toBeDisabled();
  await expect(page.getByLabel("Upload personal details page")).toHaveCount(0);
  await page.getByLabel("Upload traveller photo").setInputFiles({ name: "photo.png", mimeType: "image/png", buffer: imageBytes });
  await page.getByRole("heading", { name: "Traveller photo" }).scrollIntoViewIfNeeded();
  await expect(page.getByRole("img", { name: "Traveller photo" })).toBeVisible();
  await page.getByRole("combobox", { name: "Passenger's relationship" }).selectOption("spouse");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect.poll(() => currentDraft().collection?.qualifier_selection_token).toBe("current-trip-selection");
  await page.reload(); await page.getByRole("button", { name: /Continue from where you left/ }).click();
  await expect(page.getByText("Qualifier relationship saved")).toBeVisible();
  await page.getByRole("heading", { name: "Traveller photo" }).scrollIntoViewIfNeeded();
  await expect(page.getByRole("img", { name: "Traveller photo" })).toHaveCount(0);
  expect(currentDraft().documents).toEqual([]);
  await page.getByLabel("Upload traveller photo").setInputFiles({ name: "photo-resumed.png", mimeType: "image/png", buffer: imageBytes });
  await expect(page.getByRole("img", { name: "Traveller photo" })).toBeVisible();
  await expect(page.getByLabel("Passport Number", { exact: true })).toHaveValue("A1234567");
  expect(currentDraft().collection?.visa_photo_source).toBe("file");
  expect(calls.filter((call) => call.path.endsWith("/complete"))).toHaveLength(0);
  expect(calls.filter((call) => call.method === "POST" && call.path.includes("/draft/documents/"))).toHaveLength(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("returning-required-photo-320.png"), fullPage: true });
  await page.getByRole("checkbox", { name: /reviewed my passport/ }).check();
  await page.getByRole("button", { name: "Submit trip details" }).click();
  await expect(page.getByRole("heading", { name: "Your trip details are saved" })).toBeVisible();
  expect(calls.filter((call) => call.path.endsWith("/draft/complete"))).toHaveLength(1);
});
