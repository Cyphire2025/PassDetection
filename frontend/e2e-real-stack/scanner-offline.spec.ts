import { expect, test } from "@playwright/test";
import { browserSeed, cameraFrame, installCameraFrames } from "./workflow-support";

test("decoded camera QR is durably queued offline then reconciled once by the real API", async ({ page, context }, info) => {
  test.setTimeout(100_000);
  const seed = browserSeed(); const fixture = seed.browser_workflows[info.project.name];
  await page.setViewportSize({ width: 390, height: 844 });
  const ensureCameraFrames = await installCameraFrames(page, fixture.qr_payload);
  await page.goto("/login?from=%2Fcoordinator");
  await page.getByLabel("Email address").fill(fixture.email);
  await page.locator("#login-password").fill(fixture.password);
  const renewal = page.waitForResponse((response) => response.url().endsWith("/api/v1/auth/refresh") && response.status() === 200);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/coordinator$/);
  await renewal;
  await page.goto(`/coordinator/groups/${seed.group_id}/scanner?sessionId=${fixture.session_id}`);
  // Verify installation in this document too: the failed WebKit trace had
  // reached the scanner without the early-navigation camera fixture.
  await ensureCameraFrames();
  expect(await page.evaluate(() => Object.hasOwn(navigator.mediaDevices, "getUserMedia"))).toBe(true);
  await expect(page.getByText(`Browser ${info.project.name} activity`, { exact: true })).toBeVisible();
  await expect(page.getByText(/Verifying signed offline roster|Signed offline readiness is unavailable/)).toHaveCount(0, { timeout: 30_000 });
  // WebKit can require a user gesture before playing a synthetic canvas stream.
  // Exercise the existing explicit retry action; do not override permissions.
  const retryCamera = page.getByRole("button", { name: "Retry camera", exact: true });
  if (await retryCamera.isVisible()) await retryCamera.click();
  await info.attach("synthetic-camera-source", { contentType: "application/json", body: JSON.stringify(await page.evaluate(() => {
    const video = document.querySelector("video");
    return { source: (window as unknown as { qualificationCameraSource: unknown }).qualificationCameraSource, overridePresent: Object.hasOwn(navigator.mediaDevices, "getUserMedia"), video: video && { muted: video.muted, autoplay: video.autoplay, readyState: video.readyState, paused: video.paused } };
  })) });
  await expect.poll(() => page.locator("video").evaluate((video: HTMLVideoElement) => video.readyState)).toBeGreaterThanOrEqual(2);
  const pending = page.getByText("Pending", { exact: true }).locator("..");
  const counted = page.getByText("Counted", { exact: true }).locator("..");
  await expect(pending).toHaveText("Pending0");
  const before = Number((await counted.innerText()).replace(/\D/g, ""));
  await context.setOffline(true);
  await expect(page.getByText("Offline mode", { exact: true })).toBeVisible();
  await cameraFrame(page, true);
  await expect(pending).toHaveText("Pending1", { timeout: 20_000 });
  await cameraFrame(page, false);
  await expect(counted).toHaveText(`Counted${before}`);
  const records = await page.evaluate(async () => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open("passdetection-tour-ops"); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    try { return await new Promise<unknown[]>((resolve, reject) => {
      const request = db.transaction("pending-attendance-scans").objectStore("pending-attendance-scans").getAll();
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    }); } finally { db.close(); }
  });
  expect(records).toHaveLength(1);
  expect(JSON.stringify(records)).not.toContain(fixture.qr_payload);
  await page.screenshot({ path: info.outputPath("offline-encrypted-queue.png"), fullPage: true });
  await context.setOffline(false);
  await expect(pending).toHaveText("Pending0", { timeout: 30_000 });
  await expect(counted).toHaveText(`Counted${before + 1}`);
  await cameraFrame(page, true);
  await expect(page.getByText(/already (?:counted|scanned)|duplicate/i).first()).toBeVisible({ timeout: 15_000 });
  await cameraFrame(page, false);
  await expect(counted).toHaveText(`Counted${before + 1}`);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
