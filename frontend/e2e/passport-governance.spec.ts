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
    access_token_expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
  };
}

for (const role of ["agency_staff", "agency_manager"] as const) {
  for (const width of [1280, 390]) {
    test(`${role} group deletion controls match server permissions at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await installAdminCookie(page);
      const account = { ...admin, role };
      let mutations = 0;
      await page.route("**/api/v1/**", async (route) => {
        const url = new URL(route.request().url());
        if (url.pathname === "/api/v1/auth/refresh") return json(route, { ...authenticatedResponse(), user: account });
        if (url.pathname === "/api/v1/auth/me") return json(route, account);
        if (url.pathname === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
        if (url.pathname === "/api/v1/upload-links" && route.request().method() === "GET") {
          return json(route, url.searchParams.get("status_filter") === "archived"
            ? [{ ...groupLink, id: "archived-group", name: "Archived trip", status: "archived" }]
            : [groupLink]);
        }
        if (route.request().method() === "DELETE") mutations += 1;
        return json(route, []);
      });
      await page.goto("/upload-links");
      await expect(page.getByRole("heading", { name: "Group Links", level: 1 })).toBeVisible();
      await expect(page.getByRole("button", { name: "Close", exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Edit", exact: true }).first()).toBeVisible();
      await expect(page.getByRole("button", { name: "Delete", exact: true })).toHaveCount(0);
      if (role === "agency_staff") {
        await expect(page.getByRole("button", { name: "Archive", exact: true })).toHaveCount(0);
      } else {
        await page.getByRole("button", { name: "Archive", exact: true }).click();
        await expect(page.getByRole("dialog", { name: "Archive Group" })).toBeVisible();
        await page.getByRole("button", { name: "Cancel", exact: true }).click();
      }
      expect(mutations).toBe(0);
    });
  }
}

test("All Groups opens Save As from the download click, supports cancel and rename, and increases suggested filenames", async ({ page }) => {
  await installAdminCookie(page);
  type SaveEvent = {
    type: "picker" | "write" | "close";
    suggestedName?: string;
    selectedName?: string;
    active?: boolean;
    text?: string;
  };
  const saveEvents: SaveEvent[] = [];
  const browserErrors: string[] = [];
  const exportBodies: unknown[] = [];
  let browserDownloads = 0;
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("download", () => { browserDownloads += 1; });
  await page.exposeFunction("recordSavePickerEvent", (event: SaveEvent) => {
    saveEvents.push(event);
  });
  await page.addInitScript(() => {
    // Headless Chromium cannot drive Windows Save As. Keep the native boundary
    // mocked while exercising the real click, mutation, request and stream.
    const report = (window as unknown as Window & {
      recordSavePickerEvent: (event: {
        type: "picker" | "write" | "close";
        suggestedName?: string;
        selectedName?: string;
        active?: boolean;
        text?: string;
      }) => Promise<void>;
    }).recordSavePickerEvent;
    let attempts = 0;
    Object.defineProperty(window, "showSaveFilePicker", {
      configurable: true,
      value: async ({ suggestedName }: { suggestedName: string }) => {
        attempts += 1;
        const selectedName = `Staff renamed export ${attempts}.xlsx`;
        const active = navigator.userActivation.isActive;
        await report({ type: "picker", suggestedName, selectedName, active });
        if (attempts === 1) throw new DOMException("User cancelled Save As", "AbortError");
        return {
          name: selectedName,
          createWritable: async () => ({
            write: async (chunk: Uint8Array) => {
              await report({ type: "write", selectedName, text: new TextDecoder().decode(chunk) });
            },
            close: async () => { await report({ type: "close", selectedName }); },
            abort: async () => undefined,
          }),
        };
      },
    });
  });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/v1/auth/refresh") return json(route, authenticatedResponse());
    if (pathname === "/api/v1/auth/me") return json(route, admin);
    if (pathname === "/api/v1/notifications/feed") {
      return json(route, { items: [], unread_count: 0, next_cursor: null });
    }
    if (pathname === "/api/v1/passports/groups") return json(route, [groupSummary]);
    if (pathname === "/api/v1/passports/groups/export-fields") {
      return json(route, {
        group_ids: [groupLink.id],
        fields: [],
        grouping_fields: [],
        default_selected_fields: [],
        default_group_by_field: null,
      });
    }
    if (pathname === "/api/v1/passports/groups/export.xlsx") {
      exportBodies.push(request.postDataJSON());
      await route.fulfill({
        status: 200,
        contentType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers: { "content-disposition": 'attachment; filename="same-server-name.xlsx"' },
        body: "e2e-selected-groups-export",
      });
      return;
    }
    return json(route, request.method() === "GET" ? [] : {});
  });

  await page.goto("/passports");
  await expect(page.getByRole("heading", { name: "All Groups", level: 1 })).toBeVisible();
  await expect(page.locator("[data-nextjs-dialog]")).toHaveCount(0);
  await page.getByRole("checkbox", { name: `Select ${groupLink.name}` }).click();
  await page.getByRole("button", { name: "Export Selected", exact: true }).click();
  const options = page.getByRole("dialog", { name: "Export selected groups" });
  const downloadButton = options.getByRole("button", { name: "Download Excel" });
  await expect(downloadButton).toBeEnabled();

  // Cancelling Save As keeps the export options usable and makes no export request.
  await downloadButton.click();
  await expect.poll(() => saveEvents.filter((event) => event.type === "picker").length).toBe(1);
  await expect(downloadButton).toBeEnabled();
  await expect(options).toBeVisible();
  await expect(options.getByRole("alert")).toHaveCount(0);
  expect(exportBodies).toHaveLength(0);
  expect(saveEvents.filter((event) => event.type === "write")).toHaveLength(0);

  await downloadButton.click();
  await expect.poll(() => saveEvents.filter((event) => event.type === "close").length).toBe(1);
  await expect(options).toHaveCount(0);
  expect(exportBodies).toEqual([{
    group_ids: [groupLink.id], supplemental_fields: [], group_by_field: "none",
  }]);

  await page.getByRole("button", { name: "Export Selected", exact: true }).click();
  await downloadButton.click();
  await expect.poll(() => saveEvents.filter((event) => event.type === "close").length).toBe(2);
  await expect(options).toHaveCount(0);
  const pickerEvents = saveEvents.filter((event) => event.type === "picker");
  expect(pickerEvents).toHaveLength(3);
  expect(pickerEvents.every((event) => event.active)).toBe(true);
  const suggestions = pickerEvents.map((event) => event.suggestedName!);
  expect(new Set(suggestions).size).toBe(3);
  const sequences = suggestions.map((name) => {
    expect(name).toMatch(/^selected-groups-passports-.*-\d+\.xlsx$/);
    return Number(name.match(/-(\d+)\.xlsx$/)![1]);
  });
  expect(sequences[1]).toBe(sequences[0] + 1);
  expect(sequences[2]).toBe(sequences[1] + 1);
  for (const selectedName of ["Staff renamed export 2.xlsx", "Staff renamed export 3.xlsx"]) {
    expect(saveEvents.filter((event) => event.type === "write" && event.selectedName === selectedName)
      .map((event) => event.text).join("")).toBe("e2e-selected-groups-export");
  }
  expect(exportBodies).toHaveLength(2);
  expect(browserDownloads).toBe(0);
  expect(browserErrors).toEqual([]);
});

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

test("permanent deletion shows a conflict after identity verification and succeeds only on a manual retry", async ({ page }) => {
  await installAdminCookie(page);
  let deleted = false;
  const deletionQueries: string[] = [];
  const verificationBodies: unknown[] = [];
  const conflictMessage = "Restore all active replacement and rejection decisions before permanently deleting this group.";
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/v1/auth/refresh") return json(route, authenticatedResponse());
    if (url.pathname === "/api/v1/auth/me") return json(route, admin);
    if (url.pathname === "/api/v1/notifications/feed") {
      return json(route, { items: [], unread_count: 0, next_cursor: null });
    }
    if (url.pathname === "/api/v1/auth/mfa/step-up") {
      verificationBodies.push(request.postDataJSON());
      return json(route, authenticatedResponse());
    }
    if (url.pathname === "/api/v1/upload-links" && request.method() === "GET") {
      return json(route, url.searchParams.get("status_filter") === "archived" && !deleted
        ? [{ ...groupLink, status: "archived", closed_at: "2026-09-24T00:00:00Z" }]
        : []);
    }
    if (url.pathname === `/api/v1/upload-links/${groupLink.id}/permanent` && request.method() === "DELETE") {
      deletionQueries.push(url.search);
      if (deletionQueries.length === 1) {
        return json(route, { error: { code: "STEP_UP_REQUIRED", message: "Confirm your identity before deleting this group." } }, 403);
      }
      if (deletionQueries.length === 2) {
        return json(route, { error: { code: "PASSPORT_ROSTER_DECISION_ACTIVE", message: conflictMessage } }, 409);
      }
      deleted = true;
      await route.fulfill({ status: 204 });
      return;
    }
    return json(route, request.method() === "GET" ? [] : {});
  });

  await page.goto("/upload-links");
  const archivedRegion = page.getByRole("region", { name: "Archived groups" });
  const row = archivedRegion.getByRole("row").filter({ hasText: groupLink.name });
  await row.getByRole("button", { name: "Delete", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Delete Archived Group" });
  await dialog.getByRole("button", { name: "Delete passport records" }).click();
  const stepUp = page.getByRole("dialog", { name: "Confirm this sensitive action" });
  await expect(stepUp).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Close dialog" })).toBeDisabled();
  await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeDisabled();
  await stepUp.getByRole("textbox", { name: "Verification code" }).fill("123456");
  await stepUp.getByRole("button", { name: "Verify and continue" }).click();
  await expect(dialog.getByRole("alert")).toContainText(conflictMessage);
  await expect(stepUp).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "Delete passport records" })).toBeEnabled();
  expect(deletionQueries).toEqual(["?retain_records=false", "?retain_records=false"]);
  expect(verificationBodies).toEqual([{ code: "123456" }]);
  expect(deleted).toBe(false);

  await dialog.getByRole("button", { name: "Delete passport records" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText("No archived Group Links")).toBeVisible();
  expect(deletionQueries).toEqual(Array(3).fill("?retain_records=false"));
  expect(verificationBodies).toHaveLength(1);
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

test("the group workspace contains no removed legal-hold controls", async ({ page }) => {
  // Scheduled retention remains a backend concern; legal-hold controls have been removed.
  await installAdminCookie(page);
  let retentionRequests = 0;
  await page.route("**/api/v1/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/v1/auth/refresh") return json(route, authenticatedResponse());
    if (pathname === "/api/v1/auth/me") return json(route, admin);
    if (pathname === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (pathname === "/api/v1/passports/groups") return json(route, [groupSummary]);
    if (pathname === `/api/v1/passports/groups/${groupLink.id}/submissions-view`) {
      return json(route, {
        items: [submission], ordered_submission_ids: [submission.id],
        ordered_selection_snapshot: [{ submission_id: submission.id, extraction_revision: 4 }],
        group_total: 1, total: 1, page: 1, page_size: 50, total_pages: 1,
        returned_count: 1, cluster_boundaries_preserved: true, expiry_alerts: [],
      });
    }
    if (pathname.includes("passport-retention")) retentionRequests += 1;
    return json(route, []);
  });
  await page.goto(`/passports/groups/${groupLink.id}`);
  await expect(page.getByRole("heading", { name: groupLink.name, level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Passport retention & legal hold" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Release legal hold" })).toHaveCount(0);
  expect(retentionRequests).toBe(0);
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
