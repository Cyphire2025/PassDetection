import { expect, test, type Locator, type Page, type Route } from "@playwright/test";

const admin = {
  id: "image-editor-admin",
  email: "editor@example.test",
  full_name: "Document Review Team",
  role: "agency_admin",
  agency_id: "image-editor-agency",
  is_active: true,
  capabilities: [],
  last_login_at: null,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};

const groupId = "image-editor-group";
const submissionId = "image-editor-submission";
const imageRoot = `/api/v1/passports/${submissionId}/images`;
const imageRevision = 7;
const groupSummary = {
  group_id: groupId,
  group_name: "Document review preview",
  group_status: "active",
  total_passports: 1,
  pending_review_count: 1,
  confirmed_count: 0,
  failed_count: 0,
  latest_submission_at: "2026-09-01T00:00:00Z",
  destination: "Singapore",
  travel_date: "2026-11-01",
  return_date: "2026-11-08",
  timezone: "Asia/Singapore",
  package_name: null,
  departure_cities: [],
  custom_questions: [],
  custom_details: [],
  notes: null,
};
const submission = {
  id: submissionId,
  group_id: groupId,
  agency_id: admin.agency_id,
  client_name: "Sample document",
  client_email: null,
  client_phone: null,
  departure_city: null,
  submission_mode: "single",
  family_group_id: null,
  image_s3_key: "synthetic/front.svg",
  image_url: `${imageRoot}/passport_front`,
  passport_photo_url: `${imageRoot}/visa_photo`,
  passport_photo_s3_key: "synthetic/photo.svg",
  passport_back_s3_key: null,
  passport_back_url: null,
  staff_metadata: null,
  custom_answers: [],
  custom_detail_answers: [],
  extraction_status: "ready_for_review",
  extraction_revision: 4,
  status: "needs_review",
  extracted_fields: {},
  confirmed_fields: null,
  extraction_conflicts: [],
  post_submission_verification: null,
  duplicate_cluster_id: null,
  duplicate_cluster_size: 1,
  duplicate_cluster_member_ids: [],
  processing_job_status: "succeeded",
  processing_progress: 100,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};

type CropRequest = {
  x: number;
  y: number;
  width: number;
  height: number;
  rotation_degrees: number;
  sharpness: number;
  expected_revision: number;
};

async function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

// Intentionally synthetic artwork: no passport scans, faces, or personal details.
function sampleDocument(width: number, height: number) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 1600 1000" preserveAspectRatio="none">
    <defs><pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="#cadfe0" stroke-width="1"/></pattern></defs>
    <rect width="1600" height="1000" fill="#edf5f2"/><rect x="40" y="40" width="1520" height="920" rx="24" fill="url(#grid)" stroke="#679492" stroke-width="3"/>
    <rect x="90" y="90" width="1420" height="130" rx="12" fill="#103d52"/>
    <text x="140" y="174" fill="white" font-family="sans-serif" font-size="46" font-weight="bold">DOCUMENT EDITOR · SAMPLE ONLY</text>
    <rect x="90" y="275" width="380" height="460" rx="16" fill="#d5e7e8"/>
    <circle cx="280" cy="430" r="78" fill="#7caaa8"/><path d="M140 695v-50a140 140 0 0 1 280 0v50" fill="#7caaa8"/>
    <g fill="#335867" font-family="sans-serif"><text x="540" y="328" font-size="30">PREVIEW DOCUMENT</text><text x="540" y="390" font-size="52" font-weight="bold">Clarity in every detail.</text><text x="540" y="495" font-size="30">Synthetic image for layout verification</text><text x="540" y="565" font-size="30">Crop · Straighten · Sharpen</text></g>
    <path d="M540 625H1430M540 680H1350M90 805H1500M90 860H1500" stroke="#9bb9b9" stroke-width="18"/>
    <g fill="#b6ce30"><circle cx="60" cy="60" r="14"/><circle cx="1540" cy="60" r="14"/><circle cx="60" cy="940" r="14"/><circle cx="1540" cy="940" r="14"/></g>
  </svg>`;
}

async function installEditorFixture(
  page: Page,
  dimensions: { width: number; height: number },
  existingCrop = false,
) {
  const saved: CropRequest[] = [];
  const reset: unknown[] = [];
  const unexpected: string[] = [];
  await page.context().addCookies([{
    name: "access_token", value: "isolated-image-editor-session", domain: "127.0.0.1",
    path: "/", httpOnly: true, sameSite: "Lax",
  }]);
  const state = (imageType: string) => ({
    image_type: imageType,
    original_url: `${imageRoot}/${imageType}/original`,
    editable_source_url: `${imageRoot}/${imageType}/original`,
    cropped_url: `${imageRoot}/${imageType}`,
    crop: existingCrop ? { x: 0.1, y: 0.1, width: 0.8, height: 0.8, rotation_degrees: 0 } : null,
    revision: imageRevision,
    source_width: dimensions.width,
    source_height: dimensions.height,
    sharpness: 1,
    sharpness_algorithm_version: 2,
    ai_edited: false,
  });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/v1/auth/refresh") return json(route, {
      status: "authenticated", user: admin, token_type: "bearer",
      access_token_expires_at: "2099-09-01T00:00:00Z",
    });
    if (pathname === "/api/v1/auth/me") return json(route, admin);
    if (pathname === "/api/v1/notifications/feed") return json(route, {
      items: [], unread_count: 0, next_cursor: null,
    });
    if (pathname === "/api/v1/passports/groups") return json(route, [groupSummary]);
    if (pathname === `/api/v1/passports/groups/${groupId}/submissions-view`) return json(route, {
      items: [submission], ordered_submission_ids: [submissionId],
      ordered_selection_snapshot: [{ submission_id: submissionId, extraction_revision: 4 }],
      group_total: 1, total: 1, page: 1, page_size: 50, total_pages: 1,
      returned_count: 1, cluster_boundaries_preserved: true, expiry_alerts: [],
    });
    if (pathname === `/api/v1/admin/groups/${groupId}/passport-retention`) return json(route, {
      group_id: groupId, passport_purge_at: null, passport_retention_days_applied: null,
      legal_hold: false, legal_hold_reason: null, legal_hold_set_at: null,
      legal_hold_set_by_user_id: null,
    });
    if (pathname === `/api/v1/upload-links/${groupId}/whatsapp-links`) return json(route, {
      client_group_id: groupId, broadcasts: [], broadcast_count: 0, recipient_count: 0, can_manage: true,
    });
    if (pathname === `/api/v1/document-distribution/groups/${groupId}/whatsapp-deliveries/tracking`) return json(route, {
      group_id: groupId, poll_after_seconds: null,
      counts: { total: 0, queued: 0, sent: 0, delivered: 0, read: 0, failed: 0, delivery_unknown: 0 },
      deliveries: [],
    });
    if (pathname === "/api/v1/upload-links") return json(route, []);
    if (pathname.startsWith(imageRoot)) {
      const imageType = pathname.split("/")[6];
      if (pathname.endsWith("/crop")) {
        if (request.method() === "PUT") saved.push(request.postDataJSON() as CropRequest);
        if (request.method() === "DELETE") reset.push(request.postDataJSON());
        return json(route, state(imageType));
      }
      if (pathname.endsWith("/library")) return json(route, { items: [{
        id: "original-sample", image_type: imageType, image_url: `${imageRoot}/${imageType}/original`,
        source: "original", created_at: "2026-09-01T00:00:00Z", is_current: true,
      }] });
      if (pathname.endsWith("/ai-jobs/active")) return json(route, null);
      if (request.method() === "GET") return route.fulfill({
        contentType: "image/svg+xml", body: sampleDocument(dimensions.width, dimensions.height),
      });
    }
    if (pathname.startsWith("/api/v1/telemetry")) return json(route, {});
    unexpected.push(`${request.method()} ${pathname}`);
    return json(route, { error: { code: "UNMOCKED_TEST_REQUEST", message: pathname } }, 400);
  });
  return { saved, reset, unexpected };
}

async function openEditor(page: Page, label = "Passport front") {
  await page.goto(`/passports/groups/${groupId}?view=docs`);
  await expect(page.getByRole("heading", { name: groupSummary.group_name, level: 1 })).toBeVisible();
  const cell = page.getByRole("cell").filter({
    has: page.getByRole("link", { name: `Open ${label} in a new tab` }),
  });
  await cell.getByRole("button", { name: "Edit", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: `Edit ${label}` });
  await expect(dialog).toBeVisible();
  const canvas = dialog.locator(`canvas[aria-label="Editable ${label}"]`);
  await expect(canvas).toBeVisible();
  await expect.poll(() => canvas.evaluate((node: HTMLCanvasElement) => node.width)).toBeGreaterThan(300);
  return { dialog, canvas };
}

async function expectInsideViewport(page: Page, locator: Locator) {
  await expect(locator).toBeInViewport({ ratio: 1 });
  const bounds = await locator.boundingBox();
  const viewport = page.viewportSize()!;
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.y).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width + 1);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height + 1);
}

for (const viewport of [{ width: 1280, height: 800 }, { width: 1366, height: 650 }, { width: 390, height: 844 }, { width: 320, height: 740 }]) {
  for (const orientation of ["landscape", "portrait"] as const) {
    test(`image stays fitted with reachable controls: ${orientation} at ${viewport.width}x${viewport.height}`, async ({ page }, testInfo) => {
      await page.setViewportSize(viewport);
      const dimensions = orientation === "landscape" ? { width: 1600, height: 1000 } : { width: 1000, height: 1600 };
      const fixture = await installEditorFixture(page, dimensions);
      const { dialog, canvas } = await openEditor(page);
      await expectInsideViewport(page, canvas);
      await expectInsideViewport(page, dialog.getByRole("button", { name: "Save edits", exact: true }));
      if (viewport.width < 1024) {
        const previewBounds = await dialog.locator("[data-image-preview-viewport]").boundingBox();
        expect(previewBounds!.height).toBeGreaterThanOrEqual(220);
        const buttons = ["Reset edits", "Cancel", "Save edits"].map(name => dialog.getByRole("button", { name, exact: true }));
        for (const button of buttons) await expectInsideViewport(page, button);
        const boxes = await Promise.all(buttons.map(button => button.boundingBox()));
        for (let first = 0; first < boxes.length; first += 1) {
          for (let second = first + 1; second < boxes.length; second += 1) {
            const a = boxes[first]!;
            const b = boxes[second]!;
            const overlapWidth = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x));
            const overlapHeight = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
            expect(overlapWidth * overlapHeight).toBe(0);
          }
        }
      }
      const canvasBounds = await canvas.boundingBox();
      expect(canvasBounds!.width / canvasBounds!.height).toBeCloseTo(dimensions.width / dimensions.height, 1);
      await page.screenshot({ path: testInfo.outputPath("image-editor-fitted.png"), fullPage: false });
      const sharpness = dialog.getByRole("slider", { name: "Sharpness", exact: true });
      await sharpness.scrollIntoViewIfNeeded();
      await expectInsideViewport(page, sharpness);
      await expectInsideViewport(page, dialog.getByRole("button", { name: "Save edits", exact: true }));
      if (viewport.width >= 1024) await expectInsideViewport(page, canvas);
      await page.screenshot({ path: testInfo.outputPath("image-editor-adjustments.png"), fullPage: false });
      await dialog.getByRole("button", { name: "Zoom in preview", exact: true }).scrollIntoViewIfNeeded();
      await dialog.getByRole("button", { name: "Zoom in preview", exact: true }).click();
      await expect.poll(async () => (await canvas.boundingBox())!.width).toBeGreaterThan(canvasBounds!.width);
      await dialog.getByRole("button", { name: "Fit image", exact: true }).click();
      await expect.poll(async () => (await canvas.boundingBox())!.width).toBeCloseTo(canvasBounds!.width, 0);
      await expectInsideViewport(page, canvas);
      await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
      await expect(dialog).toHaveCount(0);
      expect(fixture.saved).toEqual([]);
      expect(fixture.unexpected).toEqual([]);
    });
  }
}

test("crop, straighten, rotate and sharpen keep the normalized revision-aware save contract", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 800 });
  const fixture = await installEditorFixture(page, { width: 1600, height: 1000 });
  const { dialog, canvas } = await openEditor(page);
  const initialBounds = (await canvas.boundingBox())!;
  const corner = dialog.getByRole("button", { name: "Resize crop from top left corner" });
  const cornerBounds = (await corner.boundingBox())!;
  await page.mouse.move(cornerBounds.x + cornerBounds.width / 2, cornerBounds.y + cornerBounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(cornerBounds.x + cornerBounds.width / 2 + initialBounds.width * 0.1,
    cornerBounds.y + cornerBounds.height / 2 + initialBounds.height * 0.1, { steps: 6 });
  await page.mouse.up();
  const cropFrame = dialog.getByRole("group", { name: "Crop frame. Use arrow keys to move it; hold Shift for larger steps." });
  const beforeKeyboard = (await cropFrame.boundingBox())!;
  await corner.focus();
  await corner.press("ArrowRight");
  const afterKeyboard = (await cropFrame.boundingBox())!;
  expect(afterKeyboard.x).toBeGreaterThan(beforeKeyboard.x);
  expect(afterKeyboard.width).toBeLessThan(beforeKeyboard.width);
  expect(afterKeyboard.x + afterKeyboard.width).toBeCloseTo(beforeKeyboard.x + beforeKeyboard.width, 0);
  const rotation = dialog.getByRole("slider", { name: "Fine rotation", exact: true });
  const sharpness = dialog.getByRole("slider", { name: "Sharpness", exact: true });
  const rotationDegrees = dialog.getByRole("spinbutton", { name: "Fine rotation degrees", exact: true });
  await rotationDegrees.fill("");
  await rotationDegrees.pressSequentially("-12");
  await rotationDegrees.press("Tab");
  await expect(rotation).toHaveValue("-12");
  await rotationDegrees.fill("0");
  await rotationDegrees.press("Tab");
  await rotation.focus();
  for (let index = 0; index < 5; index += 1) await rotation.press("ArrowRight");
  await sharpness.focus();
  for (let index = 0; index < 10; index += 1) await sharpness.press("ArrowRight");
  await dialog.getByRole("button", { name: "Rotate right 90 degrees", exact: true }).click();
  await expectInsideViewport(page, canvas);
  await dialog.getByRole("button", { name: "Save edits", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(fixture.saved).toHaveLength(1);
  expect(fixture.saved[0]).toMatchObject({ rotation_degrees: 95, sharpness: 1.5, expected_revision: imageRevision });
  const crop = fixture.saved[0];
  expect(crop.width).toBeLessThan(0.95);
  expect(crop.height).toBeLessThan(0.95);
  expect(crop.x).toBeGreaterThanOrEqual(0);
  expect(crop.y).toBeGreaterThanOrEqual(0);
  expect(crop.x + crop.width).toBeLessThanOrEqual(1.000001);
  expect(crop.y + crop.height).toBeLessThanOrEqual(1.000001);
  expect(fixture.unexpected).toEqual([]);
});

test("original-image reset and saved-image library stay available", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  const fixture = await installEditorFixture(page, { width: 1600, height: 1000 }, true);
  const { dialog } = await openEditor(page);
  await dialog.getByRole("tab", { name: "Library", exact: true }).click();
  await expect(dialog.getByRole("heading", { name: "Image library" })).toBeVisible();
  await expect(dialog.getByRole("img", { name: "Original Passport front" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Upload image", exact: true })).toBeVisible();
  await dialog.getByRole("tab", { name: "Adjust", exact: true }).click();
  await dialog.getByRole("button", { name: "Reset edits", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(fixture.reset).toEqual([{ expected_revision: imageRevision }]);
  expect(fixture.saved).toEqual([]);
  expect(fixture.unexpected).toEqual([]);
});

test("preview zoom, crop grid and local undo do not rewrite the saved document", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  const fixture = await installEditorFixture(page, { width: 1600, height: 1000 }, true);
  const { dialog } = await openEditor(page);
  const grid = dialog.getByRole("button", { name: "Show crop grid", exact: true });
  await grid.click();
  await expect(grid).toHaveAttribute("aria-pressed", "true");
  await dialog.getByRole("button", { name: "Rotate right 90 degrees", exact: true }).click();
  await dialog.getByRole("button", { name: "Full image", exact: true }).click();
  await dialog.getByRole("button", { name: "Undo changes", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "Undo changes", exact: true })).toBeDisabled();
  await dialog.getByRole("button", { name: "Zoom in preview", exact: true }).click();
  await dialog.getByRole("button", { name: "Save edits", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(fixture.saved).toEqual([{
    x: 0.1, y: 0.1, width: 0.8, height: 0.8, rotation_degrees: 0,
    sharpness: 1, expected_revision: imageRevision,
  }]);
  expect(fixture.reset).toEqual([]);
  expect(fixture.unexpected).toEqual([]);
});

test("visa-photo editor keeps its AI and library workspaces", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const fixture = await installEditorFixture(page, { width: 1000, height: 1600 });
  const { dialog, canvas } = await openEditor(page, "Visa Photo");
  await expectInsideViewport(page, canvas);
  await dialog.getByRole("tab", { name: "AI", exact: true }).click();
  await expect(dialog.getByRole("textbox")).toBeVisible();
  await dialog.getByRole("tab", { name: "Library", exact: true }).click();
  await expect(dialog.getByRole("heading", { name: "Image library" })).toBeVisible();
  await dialog.getByRole("button", { name: "Close image editor" }).click();
  await expect(dialog).toHaveCount(0);
  expect(fixture.saved).toEqual([]);
  expect(fixture.unexpected).toEqual([]);
});
