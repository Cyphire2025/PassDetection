import { expect, test, type Page, type Route } from "@playwright/test";
import { DEFAULT_UPLOAD_CONFIGURATION } from "../features/passports/types/upload-configuration";
import type { FreshDraft } from "../features/upload/api/fresh-draft.api";

const token = "synthetic-fresh-trip";
const pixel = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jPRkAAAAASUVORK5CYII=", "base64");
const group = { id: "group", name: "Synthetic Journey", token, status: "active", travel_date: "2027-12-01", return_date: "2027-12-08", departure_cities: [], custom_questions: [{ id: "meal", label: "Preferred meal", options: ["Veg", "Jain"], enabled: true, required: true }], custom_details: [{ id: "region", label: "Region", enabled: true, required: true }], staff_code_enabled: true, qualifier_relation_options: [{ code: "spouse", label: "Spouse" }], relation_with_qualifier_enabled: true, allow_files_from_device: true, require_selfie: false, upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, passport_upload_pages: ["front"], passport_live_scan: false } };
const fields = { given_names: "Synthetic", surname: "Traveller", passport_number: "TEST1234", nationality: "IND", place_of_issue: "DELHI", date_of_birth: "1990-01-01", date_of_issue: "2020-01-01", date_of_expiry: "2030-01-01", sex: "M" };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
async function setup(page: Page, options: { interruptCompletion?: boolean } = {}) {
  const drafts = new Map<string, FreshDraft>();
  const completions: string[] = [], unexpected: string[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(), path = new URL(request.url()).pathname;
    const member = request.headers()["x-upload-session-id"];
    if (path === `/api/v1/upload-links/token/${token}`) return json(route, group);
    if (path.endsWith("/qualifier-selection")) { expect(member).toBeTruthy(); return json(route, { selection_token: `qualifier-${member}` }); }
    if (path.endsWith("/prepare-file")) { expect(member).toBeTruthy(); return route.fulfill({ contentType: "image/jpeg", body: pixel }); }
    if (!path.startsWith(`/api/v1/public-drafts/${token}`)) { unexpected.push(path); return json(route, {}, 403); }
    expect(member).toBeTruthy();
    let draft = drafts.get(member);
    const resuming = !!draft && request.method() === "POST" && path === `/api/v1/public-drafts/${token}`;
    if (!draft) { draft = { id: `draft-${member}`, revision: 1, status: "active", expires_at: new Date(Date.now() + 86_400_000).toISOString(), passport_fields: {}, current_details: {}, custom_answers: {}, custom_detail_answers: {}, collection: null, verified_phone: null, documents: [], extracted_fields: {}, extraction_status: "none" }; drafts.set(member, draft); }
    const body = request.headers()["content-type"]?.includes("application/json") ? request.postDataJSON() : {};
    if (path.endsWith("/activity")) return json(route, { images_present: draft.documents.length > 0, presence_recorded: true, heartbeat_after_seconds: 60 });
    if (draft.status === "active" && (resuming || path.endsWith("/discard-documents"))) { draft.documents = []; draft.extraction_status = "none"; draft.ecr_status = "none"; draft.revision++; }
    if (path.endsWith("/discard-documents")) return json(route, draft);
    if (path.endsWith("/contact/request")) return json(route, { challenge_id: `otp-${member}`, expires_in_seconds: 600, resend_after_seconds: 1 });
    if (path.endsWith("/contact/verify")) { expect(body.challenge_id).toBe(`otp-${member}`); draft.phone_verification_id = `proof-${member}`; draft.phone_verification_expires_at = new Date(Date.now() + 3_600_000).toISOString(); return json(route, { phone_verification_id: draft.phone_verification_id, phone_number: "+919999999999", expires_in_seconds: 3600 }); }
    if (path.endsWith("/complete")) {
      expect(body.phone_verification_id).toBe(`proof-${member}`); expect(body.expected_revision).toBe(draft.revision);
      expect(draft.collection?.qualifier_selection_token).toBe(`qualifier-${member}`);
      expect(draft.current_details.staff_code).toBeTruthy(); expect(draft.custom_answers.meal).toBe("Veg"); expect(draft.custom_detail_answers.region).toBe("North");
      if (draft.collection?.submission_mode === "family") { expect(draft.collection.family_head_name).toBe("Synthetic Traveller"); expect(draft.collection.family_head_email).toBe("family@example.test"); expect(draft.collection.family_head_phone).toBe("9999999999"); }
      if (draft.status !== "submitted") completions.push(member);
      draft.status = "submitted"; draft.source_submission_id = `source-${member}`;
      if (options.interruptCompletion) { options.interruptCompletion = false; return route.abort("connectionreset"); }
      return json(route, { source_submission_id: draft.source_submission_id, status: "submitted" });
    }
    if (path.includes("/documents/")) {
      if (request.method() === "GET") return route.fulfill({ contentType: "image/jpeg", body: pixel, headers: { "cache-control": "private, no-store" } });
      expect(request.headers()["content-type"]).toContain("multipart/form-data; boundary=");
      expect(request.postData()).toContain('name="file"');
      draft.revision++; draft.documents = [{ id: `front-${member}`, side: "front", state: "ready" }]; draft.passport_fields = { ...fields }; draft.extraction_status = "succeeded"; return json(route, draft);
    }
    if (request.method() === "PUT") { expect(body.expected_revision).toBe(draft.revision); Object.assign(draft, body, { revision: draft.revision + 1 }); }
    return json(route, draft);
  });
  return { drafts, completions, unexpected };
}
async function selectFresh(page: Page, family = false) {
  await page.goto(`/upload/${token}`); await page.getByRole("button", { name: /New traveller/ }).click();
  await page.getByRole("button", { name: family ? "Family" : "Only me", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
}
async function fillMember(page: Page, family = false) {
  await page.getByRole("radio", { name: /^Self/ }).click(); await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByText("Qualifier relationship saved")).toBeVisible();
  await page.getByLabel("Upload personal details page").setInputFiles({ name: "synthetic.jpg", mimeType: "image/jpeg", buffer: pixel });
  await expect(page.getByLabel("Passport Number", { exact: true })).toHaveValue("TEST1234");
  if (family) { const relation = page.getByRole("combobox", { name: "Relationship", exact: true }); if (await relation.isEnabled()) await relation.selectOption("Spouse"); await page.getByRole("combobox", { name: "Gender", exact: true }).selectOption("Male"); }
  await page.getByLabel("Staff Code", { exact: true }).fill("STAFF-ONE");
  await page.getByLabel(/Preferred meal/).selectOption("Veg"); await page.getByLabel("Region", { exact: true }).fill("North");
  await page.getByLabel("Email", { exact: true }).fill("family@example.test"); await page.getByLabel("WhatsApp number", { exact: true }).fill("9999999999");
  await page.getByRole("button", { name: "Verify WhatsApp number", exact: true }).click();
  await page.getByLabel("Verification code", { exact: true }).fill("123456"); await page.getByRole("button", { name: "Confirm code", exact: true }).click();
  await expect(page.getByText("WhatsApp number verified")).toBeVisible();
}
for (const width of [320, 1440]) test(`fresh private draft resumes and submits at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 900 }); const state = await setup(page); const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message)); await selectFresh(page); await fillMember(page);
  await expect.poll(() => Array.from(state.drafts.values())[0]?.current_details.staff_code).toBe("STAFF-ONE");
  expect(state.completions).toEqual([]);
  const stored = await page.evaluate(() => localStorage.getItem("gc.traveller.draft.v1:synthetic-fresh-trip"));
  expect(stored).not.toMatch(/TEST1234|family@example|9999999999|STAFF-ONE/);
  await page.reload(); await page.getByRole("button", { name: /Continue from where you left/ }).click();
  await expect(page.getByLabel("Passport Number", { exact: true })).toHaveValue("TEST1234"); await expect(page.getByText("WhatsApp number verified")).toBeVisible();
  expect(Array.from(state.drafts.values())[0].documents).toEqual([]);
  await page.getByLabel("Upload personal details page").setInputFiles({ name: "synthetic-resumed.jpg", mimeType: "image/jpeg", buffer: pixel });
  await expect.poll(() => Array.from(state.drafts.values())[0].documents.length).toBe(1);
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath(`fresh-review-${width}.png`), fullPage: true });
  await page.getByRole("button", { name: "Confirm details and submit" }).click(); await expect(page.getByRole("heading", { name: "You’re all set" })).toBeVisible();
  expect(state.drafts.size).toBe(1); expect(state.completions).toHaveLength(1); expect(state.unexpected).toEqual([]); expect(errors).toEqual([]);
});
test("family members keep independent private drafts and head-first submissions", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 });
  const state = await setup(page); await selectFresh(page, true); await fillMember(page, true);
  expect(state.completions).toHaveLength(0); await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByText("Family member 2 of 2")).toBeVisible(); await expect(page.getByRole("radio", { name: /^Self/ })).toBeVisible();
  expect(state.completions).toHaveLength(1); expect(state.drafts.size).toBe(2);
  await page.reload(); await page.getByRole("button", { name: /Continue from where you left/ }).click();
  await expect(page.getByText("Family member 2 of 2")).toBeVisible(); await fillMember(page, true);
  await page.getByRole("button", { name: "Confirm details and submit" }).click(); await expect(page.getByRole("heading", { name: "You’re all set" })).toBeVisible();
  expect(state.completions).toHaveLength(2); expect(new Set(state.completions).size).toBe(2); expect(state.drafts.size).toBe(2); expect(state.unexpected).toEqual([]);
});
test("an interrupted final response resumes the submitted receipt without a duplicate", async ({ page }) => {
  const state = await setup(page, { interruptCompletion: true }); await selectFresh(page); await fillMember(page);
  await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect.poll(() => state.completions.length).toBe(1);
  await expect(page.getByRole("button", { name: "Retry", exact: true })).toBeVisible();
  await page.reload(); await page.getByRole("button", { name: /Continue from where you left/ }).click();
  await expect(page.getByRole("heading", { name: "Details submitted" })).toBeVisible();
  await page.getByRole("button", { name: "Continue", exact: true }).click(); await expect(page.getByRole("heading", { name: "You’re all set" })).toBeVisible();
  expect(state.completions).toHaveLength(1); expect(state.drafts.size).toBe(1);
});
