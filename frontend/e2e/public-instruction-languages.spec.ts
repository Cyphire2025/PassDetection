import { expect, test, type Page } from "@playwright/test";
import { DEFAULT_UPLOAD_CONFIGURATION } from "../features/passports/types/upload-configuration";
import { UPLOAD_INSTRUCTIONS } from "../features/upload/config/instruction-translations";
import { VISA_PHOTO_GUIDELINES, VISA_PHOTO_GUIDELINE_IDS } from "../features/upload/config/visa-photo-guidelines";
import { mockFreshFlow, startFresh } from "./support/public-fresh-flow";

const token = "instruction-language-test-link";

async function setup(page: Page, enabled = true) {
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
  return mockFreshFlow(page, token, { group });
}

for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`instruction language follows passport and photo guidance in the private draft on ${viewport.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    const state = await setup(page);
    await startFresh(page, token);
    await expect(page.getByRole("region", { name: "Your documents", exact: true })).toBeVisible();
    const selector = page.getByRole("combobox", { name: "Instruction language", exact: true });
    await expect(selector).toHaveValue("en");
    expect(await selector.locator("option").evaluateAll((options) => options.map((option) => (option as HTMLOptionElement).value))).toEqual(["en", "mr", "hi", "ur"]);
    await selector.selectOption("mr");
    await expect(page.getByText(UPLOAD_INSTRUCTIONS.mr.passportIntro, { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Personal Details Page", exact: true })).toBeVisible();
    for (const side of ["cover", "back_cover", "front", "back"] as const) {
      await expect(page.getByText(UPLOAD_INSTRUCTIONS.mr[side], { exact: true })).toBeVisible();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`passport-instructions-${viewport.name}.png`), fullPage: true });
    await expect(selector).toHaveValue("mr");
    await expect(page.getByText(UPLOAD_INSTRUCTIONS.mr.visaWarning, { exact: true })).toBeVisible();
    for (const id of VISA_PHOTO_GUIDELINE_IDS) {
      await expect(page.getByText(VISA_PHOTO_GUIDELINES.mr.items[id].description, { exact: true })).toBeVisible();
    }
    await selector.selectOption("ur");
    await expect(page.getByText(UPLOAD_INSTRUCTIONS.ur.visaWarning, { exact: true })).toHaveAttribute("dir", "rtl");
    const guidelines = page.getByRole("region", { name: VISA_PHOTO_GUIDELINES.ur.heading });
    await expect(guidelines).toHaveAttribute("dir", "rtl");
    await expect(guidelines.getByRole("listitem")).toHaveCount(6);
    const guidelineBounds = await guidelines.boundingBox();
    const uploadBounds = await page.getByLabel("Upload traveller photo", { exact: true }).boundingBox();
    expect(guidelineBounds).not.toBeNull();
    expect(uploadBounds).not.toBeNull();
    expect(guidelineBounds!.y + guidelineBounds!.height).toBeLessThanOrEqual(uploadBounds!.y);
    await expect(page.getByRole("heading", { name: "Traveller photo", exact: true })).toBeVisible();
    await expect(page.getByLabel("Upload traveller photo", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`visa-instructions-${viewport.name}.png`), fullPage: true });
    await page.reload();
    await page.getByRole("button", { name: /Continue from where you left/ }).click();
    await expect(selector).toHaveValue("ur");
    await expect(page.getByText(UPLOAD_INSTRUCTIONS.ur.passportIntro, { exact: true })).toHaveAttribute("dir", "rtl");
    expect(state.unexpected).toEqual([]);
    expect(state.pageErrors).toEqual([]);
    expect(state.drafts.size).toBe(1);
  });
}

test("disabled language configuration falls back to English despite a saved preference", async ({ page }) => {
  const state = await setup(page, false);
  await page.addInitScript((key) => sessionStorage.setItem(key, "mr"), `passdetection:instruction-language:${token}`);
  await startFresh(page, token);
  await expect(page.getByRole("combobox", { name: "Instruction language" })).toHaveCount(0);
  await expect(page.getByText(UPLOAD_INSTRUCTIONS.en.passportIntro, { exact: true })).toBeVisible();
  expect(state.unexpected).toEqual([]);
  expect(state.pageErrors).toEqual([]);
});
