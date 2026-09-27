import { expect, test } from "@playwright/test";
import { cameraFrame, installCameraFrames } from "../e2e-real-stack/workflow-support";

test("synthetic camera still supplies real video frames after garbage collection", async ({ page }) => {
  await page.route("http://localhost:30000/**", (route) => route.fulfill({
    contentType: "text/html",
    body: `<!doctype html><button>Start camera</button><video muted autoplay playsinline></video>
      <script>document.querySelector('button').onclick = async () => {
        const video = document.querySelector('video');
        video.srcObject = await navigator.mediaDevices.getUserMedia({ video: true });
        await video.play();
      };</script>`,
  }));
  const ensureCameraFrames = await installCameraFrames(page, `pdatt:${"a".repeat(43)}`);
  await page.goto("http://localhost:30000/camera");
  await ensureCameraFrames();
  await page.requestGC();
  await page.getByRole("button", { name: "Start camera" }).click();
  await cameraFrame(page, true);
  await expect.poll(() => page.locator("video").evaluate((video: HTMLVideoElement) => video.readyState)).toBeGreaterThanOrEqual(2);
  await page.requestGC();
  expect(await page.evaluate(() => Object.hasOwn(navigator.mediaDevices, "getUserMedia"))).toBe(true);
});
