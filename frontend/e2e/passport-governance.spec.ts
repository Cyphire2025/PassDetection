import { expect, test, type Page, type Route } from "@playwright/test";

const admin = {
  id: "e2e-admin",
  email: "admin@example.test",
  full_name: "E2E Agency Admin",
  role: "agency_admin",
  agency_id: "agency-e2e",
  is_active: true,
  last_login_at: null,
  created_at: "2026-08-22T00:00:00Z",
  updated_at: "2026-08-22T00:00:00Z",
  capabilities: [],
};

const groupLink = {
  id: "group-e2e",
  name: "Singapore 2026",
  token: "public-upload-token",
  agency_id: "agency-e2e",
  status: "active" as const,
  created_by_user_id: admin.id,
  created_at: "2026-08-22T00:00:00Z",
  closed_at: null,
  destination: "Singapore",
  travel_date: "2026-11-01",
  return_date: "2026-11-08",
  timezone: "Asia/Singapore",
  package_name: "Enterprise rehearsal",
  departure_cities: ["Delhi"],
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
  deleted_passport_count: 1,
  deletion_retained_records: false,
};

const groupSummary = {
  group_id: groupLink.id,
  group_name: groupLink.name,
  group_status: "active",
  total_passports: 1,
  pending_review_count: 1,
  confirmed_count: 0,
  failed_count: 0,
  latest_submission_at: "2026-08-22T00:00:00Z",
  destination: groupLink.destination,
  travel_date: groupLink.travel_date,
  return_date: groupLink.return_date,
  timezone: groupLink.timezone,
  package_name: groupLink.package_name,
  departure_cities: groupLink.departure_cities,
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
  notes: null,
};

const submission = {
  id: "passport-e2e",
  group_id: groupLink.id,
  agency_id: admin.agency_id,
  client_name: "Aarav Sharma",
  client_email: "aarav@example.test",
  client_phone: "+919900001234",
  departure_city: "Delhi",
  submission_mode: "single",
  family_group_id: null,
  image_s3_key: "private/passport-e2e/front.jpg",
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
  extraction_revision: 4,
  status: "needs_review",
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
  },
  confirmed_fields: null,
  extraction_conflicts: [],
  post_submission_verification: null,
  post_submission_verification_revision: 4,
  post_submission_verified_at: "2026-08-22T00:00:00Z",
  verification_reviewed_by_user_id: null,
  verification_reviewer_name: null,
  verification_reviewed_at: null,
  duplicate_cluster_id: null,
  duplicate_cluster_size: 1,
  duplicate_cluster_member_ids: [],
  duplicate_match_basis: null,
  verification_confidence: 0.72,
  overall_confidence: 0.72,
  confidence_score: null,
  mrz_raw: null,
  error_message: null,
  client_reviewed_at: "2026-08-22T00:00:00Z",
  confirmed_at: null,
  processing_job_id: null,
  processing_job_status: "succeeded",
  processing_progress: 100,
  processing_stage: "complete",
  qr_status: {
    status: "active",
    token_version: 1,
    created_at: "2026-08-22T00:00:00Z",
    expires_at: "2026-11-08T00:00:00Z",
    revoked_at: null,
  },
  created_at: "2026-08-22T00:00:00Z",
  updated_at: "2026-08-22T00:00:00Z",
};

async function json(route: Route, body: unknown, status = 200, headers = {}) {
  await route.fulfill({
    status,
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

async function installAdminCookie(page: Page) {
  await page.context().addCookies([{
    name: "access_token",
    value: "e2e-session",
    domain: "127.0.0.1",
    path: "/",
    httpOnly: true,
    sameSite: "Lax",
  }]);
}

function authenticatedResponse() {
  return {
    status: "authenticated",
    user: admin,
    token_type: "bearer",
    access_token_expires_at: "2099-08-22T13:00:00Z",
  };
}

test("group archival and permanent passport deletion require a verified destructive-action boundary", async ({ page }) => {
  await installAdminCookie(page);
  let liveGroups: Array<Record<string, unknown>> = [{ ...groupLink }];
  let archivedGroups: Array<Record<string, unknown>> = [];
  let archiveAttempts = 0;
  let stepUpBody: unknown = null;
  let permanentDeleteQuery = "";

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;
    if (pathname === "/api/v1/auth/refresh") return json(route, authenticatedResponse());
    if (pathname === "/api/v1/auth/me") return json(route, admin);
    if (pathname === "/api/v1/notifications/feed") {
      return json(route, { items: [], unread_count: 0, next_cursor: null });
    }
    if (pathname === "/api/v1/auth/mfa/step-up") {
      stepUpBody = request.postDataJSON();
      return json(route, authenticatedResponse());
    }
    if (pathname === "/api/v1/upload-links" && request.method() === "GET") {
      return json(
        route,
        url.searchParams.get("status_filter") === "archived" ? archivedGroups : liveGroups,
      );
    }
    if (pathname === `/api/v1/upload-links/${groupLink.id}/permanent` && request.method() === "DELETE") {
      permanentDeleteQuery = url.search;
      archivedGroups = [];
      await route.fulfill({ status: 204 });
      return;
    }
    if (pathname === `/api/v1/upload-links/${groupLink.id}` && request.method() === "DELETE") {
      archiveAttempts += 1;
      if (archiveAttempts === 1) {
        return json(route, {
          error: {
            code: "STEP_UP_REQUIRED",
            message: "Confirm your identity before archiving this group.",
          },
        }, 403);
      }
      const archived = {
        ...groupLink,
        status: "archived" as const,
        closed_at: "2026-08-22T13:00:00Z",
      };
      liveGroups = [];
      archivedGroups = [archived];
      return json(route, archived);
    }
    return json(route, request.method() === "GET" ? [] : {});
  });

  await page.goto("/upload-links");
  await expect(page.getByRole("heading", { name: "Group Links", level: 1 })).toBeVisible();
  const liveRow = page.getByRole("row").filter({ hasText: groupLink.name });
  await liveRow.getByRole("button", { name: "Archive" }).click();
  await expect(page.getByRole("dialog", { name: "Archive Group" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.getByRole("button", { name: "Archive Group" }).click();

  const stepUpDialog = page.getByRole("dialog", { name: "Confirm this sensitive action" });
  await expect(stepUpDialog).toBeVisible();
  await stepUpDialog.getByRole("textbox", { name: "Verification code" }).fill("123456");
  await stepUpDialog.getByRole("button", { name: "Verify and continue" }).click();

  await expect.poll(() => archiveAttempts).toBe(2);
  const archivedRegion = page.getByRole("region", { name: "Archived groups" });
  await expect(archivedRegion.getByRole("row").filter({ hasText: groupLink.name })).toBeVisible();
  expect(stepUpBody).toEqual({ code: "123456" });

  const archivedRow = archivedRegion.getByRole("row").filter({ hasText: groupLink.name });
  const deleteTrigger = archivedRow.getByRole("button", { name: "Delete" });
  await deleteTrigger.click();
  let deletionDialog = page.getByRole("dialog", { name: "Delete Archived Group" });
  await expect(deletionDialog).toBeVisible();
  await expect(deletionDialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(deletionDialog.getByRole("button", { name: "Close dialog" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(deletionDialog).toHaveCount(0);
  await expect(deleteTrigger).toBeFocused();

  await deleteTrigger.click();
  deletionDialog = page.getByRole("dialog", { name: "Delete Archived Group" });
  await deletionDialog.getByRole("button", { name: "Delete passport records" }).click();

  await expect(page.getByText("No archived Group Links")).toBeVisible();
  expect(permanentDeleteQuery).toBe("?retain_records=false");
});

test("staff can select, export, open, and manually approve a passport in a rendered browser workflow", async ({ page }) => {
  await installAdminCookie(page);
  await page.addInitScript(() => {
    // Headless Chromium cannot operate the native save dialog. Install the
    // same writable-file boundary the production stream uses so this journey
    // exercises request payload, response streaming, and completion without
    // reverting to an unbounded Blob fixture.
    Object.defineProperty(window, "showSaveFilePicker", {
      configurable: true,
      value: async () => ({
        createWritable: async () => ({
          write: async () => undefined,
          close: async () => undefined,
          abort: async () => undefined,
        }),
      }),
    });
  });
  let exportBody: unknown = null;
  let approvalBody: unknown = null;

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;
    if (pathname === "/api/v1/auth/refresh") return json(route, authenticatedResponse());
    if (pathname === "/api/v1/auth/me") return json(route, admin);
    if (pathname === "/api/v1/notifications/feed") {
      return json(route, { items: [], unread_count: 0, next_cursor: null });
    }
    if (pathname === "/api/v1/passports/groups" && request.method() === "GET") {
      return json(route, [groupSummary]);
    }
    if (pathname === `/api/v1/passports/groups/${groupLink.id}/submissions-view`) {
      return json(route, {
        items: [submission],
        ordered_submission_ids: [submission.id],
        ordered_selection_snapshot: [{ submission_id: submission.id, extraction_revision: 4 }],
        group_total: 1,
        total: 1,
        page: 1,
        page_size: 50,
        total_pages: 1,
        returned_count: 1,
        cluster_boundaries_preserved: true,
        expiry_alerts: [],
      });
    }
    if (pathname === `/api/v1/admin/groups/${groupLink.id}/passport-retention`) {
      return json(route, {
        group_id: groupLink.id,
        passport_purge_at: "2027-11-08T00:00:00Z",
        passport_retention_days_applied: 365,
        legal_hold: false,
        legal_hold_reason: null,
        legal_hold_set_at: null,
        legal_hold_set_by_user_id: null,
      });
    }
    if (pathname === `/api/v1/passports/${submission.id}` && request.method() === "GET") {
      return json(route, submission);
    }
    if (pathname === `/api/v1/passports/${submission.id}/staff-approve` && request.method() === "POST") {
      approvalBody = request.postDataJSON();
      return json(
        route,
        { ...submission, status: "staff_approved", confirmed_fields: submission.extracted_fields },
        200,
        { "x-staff-approval-outcome": "approved", "x-staff-approval-revision": "4" },
      );
    }
    if (pathname === "/api/v1/passports/export.xlsx" && request.method() === "POST") {
      exportBody = request.postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        body: "e2e-export",
      });
      return;
    }
    if (pathname === `/api/v1/upload-links/${groupLink.id}/whatsapp-links`) {
      return json(route, {
        client_group_id: groupLink.id,
        broadcasts: [],
        broadcast_count: 0,
        recipient_count: 0,
        can_manage: true,
      });
    }
    if (pathname === `/api/v1/document-distribution/groups/${groupLink.id}/whatsapp-deliveries/tracking`) {
      return json(route, {
        group_id: groupLink.id,
        poll_after_seconds: null,
        counts: { total: 0, queued: 0, sent: 0, delivered: 0, read: 0, failed: 0, delivery_unknown: 0 },
        deliveries: [],
      });
    }
    if (pathname === "/api/v1/upload-links" && request.method() === "GET") return json(route, []);
    return json(route, request.method() === "GET" ? [] : {});
  });

  await page.goto(`/passports/groups/${groupLink.id}`);
  await expect(page.getByRole("heading", { name: groupLink.name, level: 1 })).toBeVisible();
  await page.getByRole("checkbox", { name: `Select ${submission.client_name}` }).click();
  await page.getByRole("button", { name: "Open bulk actions for 1 selected submissions" }).click();
  await page.getByRole("button", { name: "Export Excel (1)" }).click();
  await expect.poll(() => exportBody).not.toBeNull();
  expect(exportBody).toEqual({ submission_ids: [submission.id] });

  await page.getByRole("link", { name: "Open" }).click();
  await expect(page).toHaveURL(new RegExp(`/passports/${submission.id}`));
  await expect(page.getByRole("heading", { name: submission.client_name, level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Approve After Manual Review" }).click();
  await expect(page.getByText("Passport approved and reviewed corrections saved.")).toBeVisible();
  expect(approvalBody).toMatchObject({ expected_extraction_revision: 4 });
});

test("an administrator can release a passport legal hold only after an audited reason and MFA step-up", async ({ page }) => {
  await installAdminCookie(page);
  let retention = {
    group_id: groupLink.id,
    passport_purge_at: "2027-11-08T00:00:00Z",
    passport_retention_days_applied: 365,
    legal_hold: true,
    legal_hold_reason: "Active legal discovery request" as string | null,
    legal_hold_set_at: "2026-08-22T00:00:00Z" as string | null,
    legal_hold_set_by_user_id: admin.id as string | null,
  };
  let updateAttempts = 0;
  let updateBody: unknown = null;

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/v1/auth/refresh") return json(route, authenticatedResponse());
    if (pathname === "/api/v1/auth/me") return json(route, admin);
    if (pathname === "/api/v1/auth/mfa/step-up") return json(route, authenticatedResponse());
    if (pathname === "/api/v1/notifications/feed") {
      return json(route, { items: [], unread_count: 0, next_cursor: null });
    }
    if (pathname === "/api/v1/passports/groups") return json(route, [groupSummary]);
    if (pathname === `/api/v1/passports/groups/${groupLink.id}/submissions-view`) {
      return json(route, {
        items: [submission],
        ordered_submission_ids: [submission.id],
        ordered_selection_snapshot: [{ submission_id: submission.id, extraction_revision: 4 }],
        group_total: 1,
        total: 1,
        page: 1,
        page_size: 50,
        total_pages: 1,
        returned_count: 1,
        cluster_boundaries_preserved: true,
        expiry_alerts: [],
      });
    }
    if (pathname === `/api/v1/admin/groups/${groupLink.id}/passport-retention`) {
      if (request.method() === "GET") return json(route, retention);
      updateAttempts += 1;
      updateBody = request.postDataJSON();
      if (updateAttempts === 1) {
        return json(route, {
          error: {
            code: "STEP_UP_REQUIRED",
            message: "Confirm your identity before changing a legal hold.",
          },
        }, 403);
      }
      retention = {
        ...retention,
        legal_hold: false,
        legal_hold_reason: null,
        legal_hold_set_at: null,
        legal_hold_set_by_user_id: null,
      };
      return json(route, retention);
    }
    if (pathname === `/api/v1/upload-links/${groupLink.id}/whatsapp-links`) {
      return json(route, {
        client_group_id: groupLink.id,
        broadcasts: [],
        broadcast_count: 0,
        recipient_count: 0,
        can_manage: true,
      });
    }
    if (pathname === `/api/v1/document-distribution/groups/${groupLink.id}/whatsapp-deliveries/tracking`) {
      return json(route, {
        group_id: groupLink.id,
        poll_after_seconds: null,
        counts: { total: 0, queued: 0, sent: 0, delivered: 0, read: 0, failed: 0, delivery_unknown: 0 },
        deliveries: [],
      });
    }
    if (pathname === "/api/v1/upload-links") return json(route, []);
    return json(route, request.method() === "GET" ? [] : {});
  });

  await page.goto(`/passports/groups/${groupLink.id}`);
  await expect(page.getByRole("heading", { name: "Passport retention & legal hold" })).toBeVisible();
  await expect(page.getByText("Active legal discovery request")).toBeVisible();
  await page.getByRole("button", { name: "Release legal hold" }).click();

  const retentionDialog = page.getByRole("dialog", { name: "Release passport legal hold" });
  await expect(retentionDialog.getByRole("textbox", { name: "Audit reason" })).toBeFocused();
  await retentionDialog.getByRole("textbox", { name: "Audit reason" }).fill("Legal review completed and release approved");
  await retentionDialog.getByRole("button", { name: "Release legal hold" }).click();

  const stepUpDialog = page.getByRole("dialog", { name: "Confirm this sensitive action" });
  await stepUpDialog.getByRole("textbox", { name: "Verification code" }).fill("123456");
  await stepUpDialog.getByRole("button", { name: "Verify and continue" }).click();

  await expect.poll(() => updateAttempts).toBe(2);
  expect(updateBody).toEqual({
    legal_hold: false,
    reason: "Legal review completed and release approved",
  });
  await expect(page.getByText("Scheduled retention active")).toBeVisible();
  await expect(page.getByText("The explicit retention schedule is active again.", { exact: false })).toBeVisible();
});

test("a direct cross-tenant passport workspace request fails closed without rendering foreign records", async ({ page }) => {
  await installAdminCookie(page);
  let deniedRequests = 0;

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/v1/auth/refresh") return json(route, authenticatedResponse());
    if (pathname === "/api/v1/auth/me") return json(route, admin);
    if (pathname === "/api/v1/notifications/feed") {
      return json(route, { items: [], unread_count: 0, next_cursor: null });
    }
    if (pathname === "/api/v1/passports/groups") return json(route, []);
    if (pathname === "/api/v1/passports/groups/foreign-group/submissions-view") {
      deniedRequests += 1;
      return json(route, {
        error: {
          code: "TENANT_ACCESS_DENIED",
          message: "This passport group is outside your agency boundary.",
        },
      }, 403);
    }
    if (pathname === "/api/v1/upload-links") return json(route, []);
    return json(route, request.method() === "GET" ? [] : {});
  });

  await page.goto("/passports/groups/foreign-group");
  await expect(page.getByText("Failed to load passport submissions for this group.")).toBeVisible();
  await expect(page.getByText("Foreign Passenger")).toHaveCount(0);
  expect(deniedRequests).toBe(1);
});
