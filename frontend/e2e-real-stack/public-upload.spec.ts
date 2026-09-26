import { expect, test } from "@playwright/test";
import { browserSeed, installSyntheticOtpDelivery, syntheticCover } from "./workflow-support";

// External OTP delivery is intercepted; a controlling service worker bypasses
// Playwright routing in WebKit. The separate scanner spec retains the real SW.
test.use({ serviceWorkers: "block" });

test("real public image upload survives reload and consumes verified contact at final submission", async ({ page }, info) => {
  test.setTimeout(120_000);
  const fixture = browserSeed().browser_workflows[info.project.name];
  await page.setViewportSize({ width: 390, height: 844 });
  await installSyntheticOtpDelivery(page);
  const uploads: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith(`/passports/upload/${fixture.public_token}`)) uploads.push(request.url());
  });
  await page.goto(`/upload/${fixture.public_token}`);
  await page.getByRole("button", { name: /Single/ }).click();
  await page.getByPlaceholder("Full name as shown on your travel documents").fill("Synthetic Browser Traveller");
  await page.getByRole("button", { name: "Upload passport images", exact: true }).click();
  const cover = await syntheticCover(page);
  for (const side of ["Front", "Back"]) {
    await page.getByLabel(`Upload Passport ${side} Cover`, { exact: true }).setInputFiles({ name: `synthetic-${side}.jpg`, mimeType: "image/jpeg", buffer: cover });
  }
  const uploaded = page.waitForResponse((response) => response.url().endsWith(`/passports/upload/${fixture.public_token}`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "Save passport pages and continue", exact: true }).click();
  const uploadResponse = await uploaded;
  expect(uploadResponse.status()).toBe(201);
  const saved = await uploadResponse.json();
  await expect(page.getByRole("textbox", { name: "Email", exact: true })).toBeVisible({ timeout: 45_000 });
  await page.reload();
  await expect(page.getByRole("textbox", { name: "Email", exact: true })).toBeVisible({ timeout: 30_000 });
  expect(uploads).toHaveLength(1);
  // Retain prior qualification rows: each new upload gets a unique synthetic
  // contact rather than deleting records or bypassing real duplicate checks.
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(`synthetic.${saved.id}@example.com`);
  const syntheticPhone = String(7_000_000_000 + Number.parseInt(saved.id.replaceAll("-", "").slice(0, 12), 16) % 1_000_000_000);
  await page.getByRole("textbox", { name: "WhatsApp active number", exact: true }).fill(syntheticPhone);
  await page.getByRole("button", { name: "Send OTP", exact: true }).click();
  await page.getByRole("textbox", { name: /6-digit.*code|verification code|OTP/i }).fill("638291");
  const verified = page.waitForResponse((response) => response.url().endsWith("/contact-otp/verify"));
  await page.getByRole("button", { name: /Verify.*continue/i }).click();
  expect((await verified).status()).toBe(200);
  const submit = page.waitForResponse((response) => response.url().endsWith("/client-submit"));
  await page.getByRole("button", { name: "Submit Traveller Details", exact: true }).click();
  const submitted = await submit;
  expect(submitted.status()).toBe(200);
  expect(new URL(submitted.url()).pathname.split("/").at(-2)).toBe(saved.id);
  const result = await submitted.json();
  expect(result.passport_cover_s3_key).toBeTruthy();
  expect(result.passport_back_cover_s3_key).toBeTruthy();
  expect(result.status).toBe("needs_review");
  expect(result.passport_cover_s3_key).not.toMatch(/^drafts\//);
  expect(result.passport_back_cover_s3_key).not.toMatch(/^drafts\//);
  await expect(page.getByRole("heading", { name: "Submitted — awaiting staff review", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: info.outputPath("real-upload-complete.png"), fullPage: true });
});
