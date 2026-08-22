import { expect, test, type Route } from "@playwright/test";

const token = "public-recovery-token";
const idempotencyKey = "recovery-key-0123456789abcdef0123456789abcdef";
const submissionId = "recovered-passport-e2e";

const group = {
  id: "group-recovery-e2e",
  name: "Recovered Singapore Group",
  token,
  agency_id: "agency-e2e",
  status: "active",
  created_by_user_id: null,
  created_at: "2026-08-22T00:00:00Z",
  closed_at: null,
  destination: "Singapore",
  travel_date: "2026-11-01",
  return_date: "2026-11-08",
  timezone: "Asia/Singapore",
  package_name: null,
  departure_cities: [],
  base_city_enabled: false,
  nearest_international_airport_enabled: false,
  staff_code_enabled: false,
  agent_employee_code_enabled: false,
  meal_preference_enabled: false,
  require_selfie: false,
  allow_files_from_device: true,
  ask_nearest_domestic_airport: false,
  relation_with_qualifier_enabled: false,
  designation_enabled: false,
  agency_dealership_name_enabled: false,
  custom_questions: [],
  custom_details: [],
  qualifier_relation_options: [],
  notes: null,
  deleted_at: null,
  deleted_passport_count: 0,
  deletion_retained_records: false,
};

const recoveredSubmission = {
  id: submissionId,
  group_id: group.id,
  agency_id: group.agency_id,
  client_name: "Passport holder",
  client_email: null,
  client_phone: null,
  departure_city: null,
  submission_mode: "single",
  family_group_id: null,
  image_s3_key: "private/recovered/front.jpg",
  image_url: null,
  passport_photo_s3_key: null,
  passport_back_s3_key: null,
  passport_photo_url: null,
  passport_back_url: null,
  thumbnail_s3_key: null,
  staff_metadata: null,
  custom_answers: [],
  custom_detail_answers: [],
  acquisition_mode: "camera",
  extraction_status: "ready_for_review",
  extraction_revision: 3,
  status: "ready_for_client_review",
  extracted_fields: {
    surname: "SHARMA",
    given_names: "AARAV",
    passport_number: "P1234567",
    nationality: "IND",
    place_of_issue: "DELHI",
    date_of_birth: "1990-01-02",
    date_of_issue: "2022-01-02",
    date_of_expiry: "2032-01-01",
    sex: "M",
    ai_verification: {
      available: true,
      status: "verified",
      provider_status: "ok",
    },
  },
  confirmed_fields: null,
  extraction_conflicts: [],
  post_submission_verification: null,
  verification_confidence: 0.94,
  overall_confidence: 0.94,
  confidence_score: null,
  mrz_raw: null,
  error_message: null,
  client_reviewed_at: null,
  confirmed_at: null,
  processing_job_id: null,
  processing_job_status: "succeeded",
  processing_progress: 1,
  processing_stage: "complete",
  qr_status: null,
  created_at: "2026-08-22T00:00:00Z",
  updated_at: "2026-08-22T00:00:00Z",
};

async function json(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

test("an interrupted public upload restores the durable submission and completes without re-uploading passport files", async ({ page }) => {
  let restoredWithCredential: string | undefined;
  let submitBody: Record<string, unknown> | null = null;
  let newUploadAttempts = 0;

  await page.addInitScript(({ groupToken, recovery }) => {
    window.sessionStorage.setItem(
      `gct:upload-recovery:${groupToken}`,
      JSON.stringify(recovery),
    );
  }, {
    groupToken: token,
    recovery: { version: 1, idempotencyKey, submissionId },
  });

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === `/api/v1/upload-links/token/${token}` && request.method() === "GET") {
      return json(route, group);
    }
    if (pathname === `/api/v1/passports/upload/${token}/${submissionId}/status`) {
      restoredWithCredential = request.headers()["x-upload-session-id"];
      return json(route, recoveredSubmission);
    }
    if (pathname === `/api/v1/passports/upload/${token}` && request.method() === "POST") {
      newUploadAttempts += 1;
      return json(route, recoveredSubmission);
    }
    if (pathname === `/api/v1/passports/${submissionId}/client-submit`) {
      submitBody = request.postDataJSON() as Record<string, unknown>;
      return json(route, {
        ...recoveredSubmission,
        status: "submitted",
        client_email: "aarav@example.test",
        client_phone: "+919900001234",
        confirmed_fields: recoveredSubmission.extracted_fields,
      });
    }
    if (pathname.includes(`/api/v1/passports/upload/${token}/${submissionId}/image/`)) {
      await route.fulfill({
        status: 200,
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=",
          "base64",
        ),
      });
      return;
    }
    return json(route, {});
  });

  await page.goto(`/upload/${token}`);
  await expect(page.getByRole("heading", { name: "Verify Passport Details" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Passport Number" })).toHaveValue("P1234567");
  await page.getByRole("textbox", { name: "Email" }).fill("aarav@example.test");
  await page.getByRole("textbox", { name: "WhatsApp active number" }).fill("+919900001234");
  await page.getByRole("button", { name: "Submit Verified Details" }).click();

  await expect(page.getByRole("heading", { name: "Details Submitted" })).toBeVisible();
  expect(restoredWithCredential).toBe(idempotencyKey);
  expect(newUploadAttempts).toBe(0);
  expect(submitBody).toMatchObject({
    group_token: token,
    client_email: "aarav@example.test",
    client_phone: "+919900001234",
    submission_mode: "single",
  });
});
