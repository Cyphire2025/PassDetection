import { expect, test, type Page } from "@playwright/test";
import { DEFAULT_UPLOAD_CONFIGURATION } from "../features/passports/types/upload-configuration";
import { UPLOAD_INSTRUCTIONS } from "../features/upload/config/instruction-translations";

const token = "instruction-language-test-link";

async function setup(page: Page, enabled = true) {
  const unexpected: string[] = [];
  const group = {
    id: "instruction-group", name: "Passport and Visa Instructions", token, status: "active",
    agency_id: "instruction-agency", created_at: "2026-09-25T00:00:00Z", destination: "Dubai",
    travel_date: "2026-11-01", return_date: "2026-11-08", timezone: "Asia/Kolkata",
    require_selfie: true, allow_files_from_device: true, relation_with_qualifier_enabled: false,
    custom_questions: [], custom_details: [], departure_cities: [], qualifier_relation_options: [],
    upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, passport_live_scan: false,
      visa_photo_live_capture: false, instruction_languages_enabled: enabled,
      instruction_languages: ["mr", "hi", "ur"], passport_upload_pages: ["cover", "back_cover", "front", "back"] },
  };
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (data: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(data) });
    if (path === `/api/v1/upload-links/token/${token}`) return json(group);
    if (path === `/api/v1/passports/upload/${token}` && request.method() === "PUT") return json({ submission_id: null });
    if (path.endsWith("/telemetry")) return json({});
    unexpected.push(`${request.method()} ${path}`);
    return route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ detail: "Unexpected isolated test request" }) });
  });
  return { group, unexpected };
}

for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`instruction language follows passport and visa steps on ${viewport.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    const state = await setup(page);
    await page.goto(`/upload/${token}`);
    await page.getByRole("button", { name: /Single/ }).click();
    await page.getByRole("button", { name: "Upload passport images", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Upload Passport Pages", exact: true })).toBeVisible();
    const selector = page.getByRole("combobox", { name: "Instruction language", exact: true });
    await expect(selector).toHaveValue("en");
    expect(await selector.locator("option").evaluateAll((options) => options.map((option) => (option as HTMLOptionElement).value))).toEqual(["en", "mr", "hi", "ur"]);
    await selector.selectOption("mr");
    await expect(page.getByText(UPLOAD_INSTRUCTIONS.mr.passportIntro, { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "3. Personal Details Page", exact: true })).toBeVisible();
    await expect(page.getByText(UPLOAD_INSTRUCTIONS.mr.front, { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`passport-instructions-${viewport.name}.png`), fullPage: true });
    await page.getByRole("button", { name: "Back to document options", exact: true }).click();
    await page.getByRole("button", { name: "Upload studio photo", exact: true }).click();
    await expect(selector).toHaveValue("mr");
    await expect(page.getByText(UPLOAD_INSTRUCTIONS.mr.visaWarning, { exact: true })).toBeVisible();
    await expect(page.getByText(UPLOAD_INSTRUCTIONS.mr.visaFraming, { exact: true })).toBeVisible();
    await selector.selectOption("ur");
    await expect(page.getByText(UPLOAD_INSTRUCTIONS.ur.visaWarning, { exact: true })).toHaveAttribute("dir", "rtl");
    await expect(page.getByText(UPLOAD_INSTRUCTIONS.ur.visaFraming, { exact: true }).locator("..")).toHaveAttribute("dir", "rtl");
    await expect(page.getByRole("heading", { name: "Upload Studio Visa Photo", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Choose studio photo", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`visa-instructions-${viewport.name}.png`), fullPage: true });
    await page.reload();
    await page.getByRole("button", { name: /Single/ }).click();
    await page.getByRole("button", { name: "Upload passport images", exact: true }).click();
    await expect(selector).toHaveValue("ur");
    await expect(page.getByText(UPLOAD_INSTRUCTIONS.ur.passportIntro, { exact: true })).toHaveAttribute("dir", "rtl");
    expect(state.unexpected).toEqual([]);
  });
}

test("disabled language configuration falls back to English despite a saved preference", async ({ page }) => {
  await setup(page, false);
  await page.addInitScript((key) => sessionStorage.setItem(key, "mr"), `passdetection:instruction-language:${token}`);
  await page.goto(`/upload/${token}`);
  await page.getByRole("button", { name: /Single/ }).click();
  await page.getByRole("button", { name: "Upload passport images", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Instruction language" })).toHaveCount(0);
  await expect(page.getByText(UPLOAD_INSTRUCTIONS.en.passportIntro, { exact: true })).toBeVisible();
});
