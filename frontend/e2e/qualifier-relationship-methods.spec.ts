import { expect, test, type Page } from "@playwright/test";

type Methods = { list: boolean; other: boolean };

async function prepareLink(page: Page, methods: Methods) {
  const token = `qualifier-methods-${Number(methods.list)}-${Number(methods.other)}`;
  const saves: Record<string, unknown>[] = [];
  let saved: Record<string, unknown> | null = null;
  const unexpected: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (pathname === `/api/v1/upload-links/token/${token}`) return json({
      id: "qualifier-test-group", name: "Dubai Client Group", token, agency_id: "test-agency",
      status: "active", created_at: "2026-09-08T00:00:00Z", destination: "Dubai",
      travel_date: "2026-11-01", return_date: "2026-11-08", timezone: "Asia/Dubai",
      departure_cities: [], require_selfie: false, allow_files_from_device: true,
      base_city_enabled: false, nearest_international_airport_enabled: false,
      staff_code_enabled: false, agent_employee_code_enabled: false, meal_preference_enabled: false,
      ask_nearest_domestic_airport: false, designation_enabled: false, agency_dealership_name_enabled: false,
      relation_with_qualifier_enabled: true, custom_questions: [], custom_details: [],
      qualifier_relation_options: methods.list ? [{ code: "spouse", label: "Spouse" }, { code: "sister", label: "Sister" }] : [],
      upload_configuration: {
        passport_enabled: true, passport_required: true, passport_live_scan: true,
        passport_upload_pages: ["front", "back"], visa_photo_required: true,
        visa_photo_live_capture: true, visa_photo_upload: true, required_fields: {},
        agent_employee_code_label: "Agent/Employee Code", agency_dealership_name_label: "Agency/Dealership Name",
        qualifier_relation_list_enabled: methods.list, qualifier_relation_other_enabled: methods.other,
      },
    });
    if (pathname.endsWith("/qualifier-selection")) {
      if (request.method() === "POST") {
        const body = request.postDataJSON();
        saves.push(body);
        saved = {
          is_self: body.is_self, relation_code: body.relation_code,
          relation_label: body.is_self ? "Self" : body.relation_code === "other" ? body.other_relation : "Spouse",
          selected_at: new Date().toISOString(), expires_at: new Date(Date.now() + 7_200_000).toISOString(),
          status: "active", selection_token: "q".repeat(43), submission_id: null,
        };
      }
      return json(saved);
    }
    if (pathname === `/api/v1/passports/upload/${token}` && request.method() === "PUT") {
      return json({ submission_id: null, status: "not_found" });
    }
    if (pathname.endsWith("/telemetry")) return json({});
    unexpected.push(`${request.method()} ${pathname}`);
    return json({ error: { message: "Unexpected test request" } }, 400);
  });
  await page.goto(`/upload/${token}`);
  await expect(page.getByRole("heading", { name: "Relation with Qualifier" })).toBeVisible();
  return { saves, errors, unexpected };
}

for (const viewport of [{ width: 1440, height: 1100 }, { width: 390, height: 950 }, { width: 320, height: 950 }]) {
  for (const methods of [{ list: true, other: false }, { list: false, other: true }, { list: true, other: true }]) {
    test(`relationship methods list=${methods.list} other=${methods.other} at ${viewport.width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize(viewport);
      const fixture = await prepareLink(page, methods);
      await expect(page.getByRole("combobox")).toHaveCount(Number(methods.list));
      await expect(page.getByRole("textbox", { name: "Specify relationship" })).toHaveCount(Number(methods.other));
      const grid = await page.getByTestId("qualifier-relationship-methods").boundingBox();
      const cards = [];
      for (const id of ["qualifier-list-card", "qualifier-other-card"]) {
        const card = page.getByTestId(id);
        if (await card.count()) cards.push((await card.boundingBox())!);
      }
      expect(cards).toHaveLength(Number(methods.list) + Number(methods.other));
      if (cards.length === 2) {
        expect(Math.abs(cards[0].width - cards[1].width)).toBeLessThan(2);
        expect(Math.abs(cards[0].y - cards[1].y)).toBeLessThan(2);
        expect(cards[1].x).toBeGreaterThan(cards[0].x + cards[0].width);
      } else expect(Math.abs(cards[0].width - grid!.width)).toBeLessThan(2);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      if (methods.other) {
        await page.getByRole("textbox", { name: "Specify relationship" }).fill("  Cousin  ");
      } else await page.getByRole("combobox").selectOption("spouse");
      await expect(page.locator('section[aria-labelledby="qualifier-choice-title"]')).toHaveCSS("opacity", "1");
      await page.screenshot({ path: testInfo.outputPath("relationship-options.png"), fullPage: true });
      await page.getByRole("button", { name: "Continue", exact: true }).click();
      await expect.poll(() => fixture.saves.length).toBe(1);
      expect(fixture.saves[0]).toEqual(methods.other
        ? { is_self: false, relation_code: "other", other_relation: "Cousin" }
        : { is_self: false, relation_code: "spouse" });
      expect(fixture.errors).toEqual([]);
      expect(fixture.unexpected).toEqual([]);
    });
  }
}

test("saved Other text restores after reload and editing creates a new selection", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 950 });
  const fixture = await prepareLink(page, { list: true, other: true });
  await page.getByRole("textbox", { name: "Specify relationship" }).fill("Cousin");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect.poll(() => fixture.saves.length).toBe(1);
  await expect(page.getByRole("button", { name: "Back", exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await expect(page.getByRole("radio", { name: /Other relationship/ })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("textbox", { name: "Specify relationship" })).toHaveValue("Cousin");
  await page.getByRole("textbox", { name: "Specify relationship" }).fill("Colleague");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect.poll(() => fixture.saves.length).toBe(2);
  expect(fixture.saves[1]).toEqual({ is_self: false, relation_code: "other", other_relation: "Colleague" });
  expect(fixture.errors).toEqual([]);
  expect(fixture.unexpected).toEqual([]);
});
