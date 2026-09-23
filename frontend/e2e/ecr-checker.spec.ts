import { expect, test, type Page, type Route } from "@playwright/test";
import type { EcrBatch, EcrItem } from "../types/ecr-checker.types";

const batchId = "00000000-0000-4000-8000-000000000001";
const user = {
  id: "ecr-test-admin", agency_id: "ecr-test-agency", email: "ecr@example.test", full_name: "ECR Test Admin",
  role: "agency_admin", is_active: true, capabilities: [], last_login_at: null,
  created_at: "2026-09-24T00:00:00Z", updated_at: "2026-09-24T00:00:00Z",
};
const emptyBatch = (): EcrBatch => ({
  batch_id: batchId, title: "ECR test", status: "uploading", total_count: 0, expected_count: 12,
  processed_count: 0, ecr_count: 0, na_count: 0, review_count: 0, failed_count: 0,
  created_at: "2026-09-24T00:00:00Z", items: [],
});
const respond = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function mockApi(page: Page, initial: EcrBatch | null = null) {
  let batch = initial;
  let activeUploads = 0;
  let maxActiveUploads = 0;
  const uploadedIds = new Set<string>();
  await page.context().addCookies([{ name: "access_token", value: "e2e-session", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  await page.addInitScript(() => Object.defineProperty(window, "showSaveFilePicker", { value: undefined, configurable: true }));
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/auth/me") return respond(route, user);
    if (path === "/api/v1/auth/refresh") return respond(route, { status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (path === "/api/v1/notifications/feed") return respond(route, { items: [], unread_count: 0, next_cursor: null });
    if (path === "/api/v1/ecr-checker/batches") {
      if (request.method() === "GET") return respond(route, batch ? [batch] : []);
      const body = request.postDataJSON();
      batch = { ...emptyBatch(), title: body.title, expected_count: body.expected_count };
      return respond(route, batch, 201);
    }
    if (path === `/api/v1/ecr-checker/batches/${batchId}`) return respond(route, batch);
    if (path === `/api/v1/ecr-checker/batches/${batchId}/items`) {
      const body = request.postDataBuffer()!.toString();
      const ids = JSON.parse(/name="client_ids"\r\n\r\n([^\r]+)/.exec(body)![1]) as string[];
      const names = [...body.matchAll(/filename="([^"]+)"/g)].map((match) => match[1]);
      expect(ids.length).toBeLessThanOrEqual(5);
      expect(ids.length).toBe(names.length);
      activeUploads++;
      maxActiveUploads = Math.max(maxActiveUploads, activeUploads);
      await new Promise((resolve) => setTimeout(resolve, 100));
      ids.forEach((id, index) => {
        expect(uploadedIds.has(id)).toBe(false);
        uploadedIds.add(id);
        batch!.items.push({ id, client_id: id, original_filename: names[index], status: "queued", result: null, reason: null });
      });
      batch!.total_count = batch!.items.length;
      activeUploads--;
      return respond(route, batch);
    }
    if (path.endsWith("/start")) {
      expect(batch!.total_count).toBe(batch!.expected_count);
      batch!.status = "completed_with_errors";
      batch!.processed_count = batch!.total_count;
      batch!.ecr_count = 1;
      batch!.review_count = 1;
      batch!.failed_count = 1;
      batch!.na_count = batch!.total_count - 3;
      batch!.items = batch!.items.map((item, index) => ({ ...item, status: index === 3 ? "failed" : "completed", result: index === 0 ? "ECR" : index === 2 ? "NEEDS_REVIEW" : index === 3 ? null : "NA", reason: index === 2 ? "Top edge cropped" : index === 3 ? "Provider unavailable" : null }));
      return respond(route, batch);
    }
    if (path.endsWith("/export.xlsx")) return route.fulfill({ contentType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers: { "content-disposition": 'attachment; filename="ECR-results.xlsx"' }, body: Buffer.from("mock-xlsx-download") });
    if (path.endsWith("/retry")) {
      batch!.items = batch!.items.map((item) => item.status === "failed" ? { ...item, status: "completed", result: "NA", reason: null } : item);
      batch!.failed_count = 0;
      batch!.na_count++;
      return respond(route, batch);
    }
    return respond(route, []);
  });
  return { getBatch: () => batch, maxActive: () => maxActiveUploads };
}

test("Documents opens ECR, uploads in parallel, reloads results and downloads Excel", async ({ page }) => {
  const api = await mockApi(page);
  await page.goto("/documents");
  await page.getByRole("link", { name: "Check passport back pages" }).click();
  await expect(page.getByRole("heading", { name: "ECR Checker", exact: true })).toBeVisible();
  await page.getByLabel("Batch title (optional)").fill("Tomorrow passports");
  await page.locator('input[type="file"]').setInputFiles(Array.from({ length: 12 }, (_, index) => ({ name: index < 2 ? "duplicate.jpg" : `passport-${index}.jpg`, mimeType: "image/jpeg", buffer: Buffer.from(`image-${index}`) })));
  await page.getByRole("button", { name: "Upload & check ECR", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Tomorrow passports" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Download Excel" })).toBeEnabled();
  expect(api.maxActive()).toBe(3);
  expect(api.getBatch()!.items).toHaveLength(12);
  await expect(page.getByRole("cell", { name: "duplicate.jpg", exact: true })).toHaveCount(2);
  await expect(page.getByRole("cell", { name: "ECR present", exact: true })).toHaveClass(/text-red-600/);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Tomorrow passports" })).toBeVisible();
  await page.getByRole("button", { name: "Needs review (1)" }).click();
  await expect(page.getByRole("cell", { name: "Top edge cropped" })).toBeVisible();
  await page.getByRole("button", { name: "Retry failed checks" }).click();
  await expect(page.getByRole("button", { name: "Failed (0)" })).toBeVisible();
  const download = page.waitForEvent("download");
  page.once("dialog", (dialog) => dialog.accept("ECR-results.xlsx"));
  await page.getByRole("button", { name: "Download Excel" }).click();
  expect((await download).suggestedFilename()).toBe("ECR-results.xlsx");
});

test("1000 saved results paginate and fit a phone viewport", async ({ page }) => {
  const items: EcrItem[] = Array.from({ length: 1000 }, (_, index) => ({ id: String(index), client_id: String(index), original_filename: `passport-${index}.jpg`, status: "completed", result: "NA", reason: null }));
  await mockApi(page, { ...emptyBatch(), status: "completed", title: "Thousand images", total_count: 1000, expected_count: 1000, processed_count: 1000, na_count: 1000, items });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/documents/ecr-checker?batch=${batchId}`);
  await expect(page.getByText("Page 1 of 20", { exact: true })).toBeVisible();
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(51);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("cell", { name: "passport-50.jpg", exact: true })).toBeVisible();
  await page.getByLabel("Search filenames").fill("passport-999.jpg");
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
