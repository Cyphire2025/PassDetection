import { expect, test, type Page } from "@playwright/test";
import { DEFAULT_UPLOAD_CONFIGURATION } from "../features/passports/types/upload-configuration";
import { expectNoHorizontalOverflow, mockPublicContactOtp, verifyPublicContact } from "./support/public-contact-otp";

const token = "public-contact-otp-e2e";
const credential = "contact-session-0123456789abcdef0123456789abcdef";
const group = {
  id: "contact-group-e2e", name: "Singapore Traveller Details", token,
  agency_id: "contact-agency-e2e", status: "active", created_at: "2026-09-20T00:00:00Z",
  destination: "Singapore", travel_date: "2026-11-01", return_date: "2026-11-08", timezone: "Asia/Kolkata",
  require_selfie: false, allow_files_from_device: true,
  base_city_enabled: true, nearest_international_airport_enabled: false,
  staff_code_enabled: false, agent_employee_code_enabled: false, meal_preference_enabled: false,
  ask_nearest_domestic_airport: false, relation_with_qualifier_enabled: false,
  designation_enabled: false, agency_dealership_name_enabled: false, departure_cities: [],
  qualifier_relation_options: [], custom_questions: [],
  custom_details: [{ id: "additional-reference", label: "Booking reference", enabled: true, required: false }],
  upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, passport_enabled: false, passport_required: false, required_fields: { base_city: true } },
};

function draft(id: string, name = "Asha Example") {
  return {
    id, group_id: group.id, agency_id: group.agency_id, client_name: name,
    status: "ready_for_client_review", extraction_status: "ready_for_review",
    image_s3_key: "", extracted_fields: null, confirmed_fields: null,
    client_email: null, client_phone: null, custom_answers: [], custom_detail_answers: [],
    created_at: "2026-09-20T00:00:00Z", updated_at: "2026-09-20T00:00:00Z",
  };
}

async function setup(page: Page, { recovery = true, expireProof = false, rejectSecondFamilyProof = false } = {}) {
  const submissions: Record<string, unknown>[] = [];
  const submissionIds: string[] = [];
  const unexpected: string[] = [];
  const pageErrors: string[] = [];
  let uploads = 0;
  let rejectProof = expireProof;
  page.on("pageerror", error => pageErrors.push(error.message));
  if (recovery) await page.addInitScript(({ token, credential }) => {
    sessionStorage.setItem(`gct:upload-recovery:${token}`, JSON.stringify({ version: 1, idempotencyKey: credential, submissionId: "contact-draft-e2e" }));
  }, { token, credential });
  await page.route("**/api/v1/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === `/api/v1/upload-links/token/${token}`) return json(group);
    if (path.endsWith("/status")) return json(draft("contact-draft-e2e"));
    if (request.method() === "PUT" && path === `/api/v1/passports/upload/${token}`) return json({ submission_id: null });
    if (path === `/api/v1/passports/upload/${token}` && request.method() === "POST") {
      const form = await new Request(request.url(), { method: "POST", headers: request.headers(), body: request.postData() }).formData();
      return json(draft(`contact-family-${++uploads}`, String(form.get("client_name"))));
    }
    if (path.endsWith("/client-submit")) {
      submissions.push(request.postDataJSON());
      submissionIds.push(path.split("/").at(-2)!);
      if (rejectProof || (rejectSecondFamilyProof && submissions.length === 2)) {
        rejectProof = false;
        return json({ detail: { code: "CONTACT_VERIFICATION_REQUIRED", field: "phone_verification_id", message: "Verify your WhatsApp number again before submitting." } }, 400);
      }
      return json({ ...draft(path.split("/").at(-2)!), status: "submitted" });
    }
    if (path.endsWith("/telemetry")) return json({});
    unexpected.push(`${request.method()} ${path}`);
    return json({ detail: "Unexpected request in isolated browser test" }, 400);
  });
  const otp = await mockPublicContactOtp(page);
  return { submissions, submissionIds, unexpected, pageErrors, otp, getUploads: () => uploads };
}

for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`verified contact opens a separate details step on ${viewport.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    const state = await setup(page);
    await page.goto(`/upload/${token}`);
    await expect(page.getByRole("textbox", { name: "Email", exact: true })).toBeVisible();
    await expect(page.getByLabel("Base City", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("Booking reference", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Send OTP", exact: true })).toHaveCount(0);
    await page.getByRole("textbox", { name: "Email", exact: true }).fill("asha@example.com");
    await page.getByRole("textbox", { name: "WhatsApp active number", exact: true }).fill("99000");
    await expect(page.getByRole("button", { name: "Send OTP", exact: true })).toHaveCount(0);
    await page.getByRole("textbox", { name: "WhatsApp active number", exact: true }).fill("+91990000123");
    await expect(page.getByRole("button", { name: "Send OTP", exact: true })).toHaveCount(0);
    await page.getByRole("textbox", { name: "WhatsApp active number", exact: true }).fill("9900001234");
    await page.getByRole("button", { name: "Send OTP", exact: true }).click();
    await expect(page.getByRole("button", { name: /Resend OTP in/ })).toBeDisabled();
    const code = page.getByRole("textbox", { name: /6-digit.*code|verification code|OTP/i });
    await code.fill("000000");
    await page.getByRole("button", { name: /Verify.*continue/i }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Invalid or expired" })).toBeVisible();
    await expect(page.getByLabel("Base City", { exact: true })).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`contact-${viewport.name}.png`), fullPage: true });
    await code.fill("123456");
    await page.getByRole("button", { name: /Verify.*continue/i }).click();
    await expect(page.getByLabel("Base City", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Send OTP", exact: true })).toHaveCount(0);
    await expect(page.getByRole("textbox", { name: "Email", exact: true })).toHaveCount(0);
    await page.getByLabel("Base City", { exact: true }).fill("Mumbai");
    await page.getByLabel("Booking reference", { exact: true }).fill("BOOK-123");
    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`details-${viewport.name}.png`), fullPage: true });
    await page.getByRole("button", { name: "Submit Traveller Details", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Details Submitted" })).toBeVisible();
    expect(state.submissions).toHaveLength(1);
    expect(state.submissions[0]).toMatchObject({ client_email: "asha@example.com", base_city: "Mumbai", phone_verification_id: expect.any(String) });
    expect(state.otp.requests.every(request => request.credential === credential)).toBe(true);
    expect(state.getUploads()).toBe(0);
    expect(state.unexpected).toEqual([]);
    expect(state.pageErrors).toEqual([]);
  });
}

test("failed OTP delivery keeps details hidden and can be retried", async ({ page }) => {
  const state = await setup(page);
  state.otp.setDeliveryFailure(true);
  await page.goto(`/upload/${token}`);
  await page.getByRole("textbox", { name: "Email", exact: true }).fill("asha@example.com");
  await page.getByRole("textbox", { name: "WhatsApp active number", exact: true }).fill("9900001234");
  await page.getByRole("button", { name: "Send OTP", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "temporarily unavailable" })).toBeVisible();
  await expect(page.getByLabel("Base City", { exact: true })).toHaveCount(0);
  state.otp.setDeliveryFailure(false);
  await verifyPublicContact(page);
  await expect(page.getByLabel("Base City", { exact: true })).toBeVisible();
  expect(state.submissions).toHaveLength(0);
});

test("family contacts are verified separately and a partial retry skips the completed member", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const state = await setup(page, { recovery: false, rejectSecondFamilyProof: true });
  await page.goto(`/upload/${token}`);
  await page.getByRole("button", { name: /Family/ }).click();
  await page.getByPlaceholder("Full name", { exact: true }).nth(0).fill("Asha Example");
  await page.getByPlaceholder("Full name", { exact: true }).nth(1).fill("Rahul Example");
  await page.getByRole("combobox", { name: "Gender", exact: true }).nth(0).selectOption("Female");
  await page.getByRole("combobox", { name: "Gender", exact: true }).nth(1).selectOption("Male");
  await page.getByRole("combobox", { name: "Relation", exact: true }).nth(1).selectOption("Spouse");
  await page.getByRole("button", { name: "Continue to Documents", exact: true }).click();
  await page.getByRole("button", { name: "Continue to your details", exact: true }).click();
  await expect.poll(state.getUploads).toBe(1);
  await page.getByRole("button", { name: "Continue to your details", exact: true }).click();
  await expect(page.getByText("Family member 1 of 2", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Base City", { exact: true })).toHaveCount(0);
  await verifyPublicContact(page, "asha@example.com");
  await expect(page.getByText("Family member 2 of 2", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Base City", { exact: true })).toHaveCount(0);
  await verifyPublicContact(page, "rahul@example.com");
  await expect(page.getByRole("heading", { name: "Review Family Details" })).toBeVisible();
  await page.getByLabel("Base City", { exact: true }).nth(0).fill("Mumbai");
  await page.getByLabel("Base City", { exact: true }).nth(1).fill("Delhi");
  await expectNoHorizontalOverflow(page);
  await page.getByRole("button", { name: "Submit Family Details", exact: true }).click();
  await expect(page.getByText("Family member 2 of 2", { exact: true })).toBeVisible();
  await verifyPublicContact(page, "rahul@example.com");
  await expect(page.getByRole("heading", { name: "Review Family Details" })).toBeVisible();
  await expect(page.getByLabel("Base City", { exact: true }).nth(0)).toBeDisabled();
  await expect(page.getByLabel("Base City", { exact: true }).nth(1)).toHaveValue("Delhi");
  await page.getByRole("button", { name: "Submit Family Details", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Details Submitted" })).toBeVisible();
  expect(state.submissionIds).toEqual(["contact-family-1", "contact-family-2", "contact-family-2"]);
  expect(state.submissions[2]).toMatchObject({ client_email: "rahul@example.com", family_head_email: "asha@example.com", base_city: "Delhi" });
  const sendRequests = state.otp.requests.filter(request => request.path.endsWith("/request"));
  expect(sendRequests).toHaveLength(3);
  expect(sendRequests[0].credential).not.toBe(sendRequests[1].credential);
  expect(sendRequests[1].credential).toBe(sendRequests[2].credential);
  expect(state.pageErrors).toEqual([]);
  expect(state.unexpected).toEqual([]);
});

test("expired proof returns to contact verification without losing entered details", async ({ page }) => {
  const state = await setup(page, { expireProof: true });
  await page.goto(`/upload/${token}`);
  await verifyPublicContact(page);
  await page.getByLabel("Base City", { exact: true }).fill("Mumbai");
  await page.getByLabel("Booking reference", { exact: true }).fill("PRESERVED-123");
  await page.getByRole("button", { name: "Submit Traveller Details", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Email", exact: true })).toBeVisible();
  await expect(page.getByLabel("Base City", { exact: true })).toHaveCount(0);
  await verifyPublicContact(page);
  await expect(page.getByLabel("Base City", { exact: true })).toHaveValue("Mumbai");
  await expect(page.getByLabel("Booking reference", { exact: true })).toHaveValue("PRESERVED-123");
  await page.getByRole("button", { name: "Submit Traveller Details", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Details Submitted" })).toBeVisible();
  expect(state.submissions).toHaveLength(2);
  expect(state.submissions[0].phone_verification_id).not.toBe(state.submissions[1].phone_verification_id);
});
