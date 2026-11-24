import { expect, test, type Page } from "@playwright/test";
import type { FreshDraft, FreshPayload } from "../features/upload/api/fresh-draft.api";

type Methods = { list: boolean; other: boolean };

async function prepareLink(page: Page, methods: Methods) {
  const token = `qualifier-methods-${Number(methods.list)}-${Number(methods.other)}`;
  const saves: Record<string, unknown>[] = [];
  const selections = new Map<string, Record<string, unknown>>();
  const drafts = new Map<string, FreshDraft>();
  const qualifierReads: string[] = [];
  const draftPath = `/api/v1/public-drafts/${token}`;
  const unexpected: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (pathname === "/api/v1/returning/capabilities" && request.method() === "GET") return json({ enabled: false, code_label: null });
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
        const selectionToken = "q".repeat(42) + String(saves.length);
        const selection = {
          is_self: body.is_self, relation_code: body.relation_code,
          relation_label: body.is_self ? "Self" : body.relation_code === "other" ? body.other_relation : "Spouse",
          selected_at: new Date().toISOString(), expires_at: new Date(Date.now() + 7_200_000).toISOString(),
          status: "active", submission_id: null,
        };
        selections.set(selectionToken, selection);
        return json({ ...selection, selection_token: selectionToken }, 201);
      }
      const selectionToken = request.headers()["x-qualifier-selection-token"];
      const selection = selections.get(selectionToken);
      if (request.method() === "GET" && selection) {
        qualifierReads.push(selectionToken);
        return json(selection);
      }
      return json({ detail: "Qualifier selection not found" }, 404);
    }
    if (pathname === draftPath || pathname.startsWith(`${draftPath}/`)) {
      const member = request.headers()["x-upload-session-id"];
      expect(member).toBeTruthy();
      let draft = drafts.get(member);
      if (pathname === draftPath && request.method() === "POST") {
        if (!draft) {
          draft = { id: `draft-${member}`, revision: 1, status: "active",
            expires_at: new Date(Date.now() + 86_400_000).toISOString(),
            passport_fields: {}, current_details: {}, custom_answers: {}, custom_detail_answers: {},
            collection: null, verified_phone: null, documents: [], extracted_fields: {}, extraction_status: "none" };
          drafts.set(member, draft);
        } else { draft.documents = []; draft.extraction_status = "none"; draft.revision++; }
        return json(draft);
      }
      if (!draft) return json({ detail: { code: "claim_expired", message: "Your secure session expired." } }, 410);
      if (pathname === `${draftPath}/activity` && request.method() === "POST") {
        return json({ images_present: false, presence_recorded: true, heartbeat_after_seconds: 60 });
      }
      if (pathname === `${draftPath}/discard-documents` && request.method() === "POST") {
        draft.documents = []; draft.extraction_status = "none"; draft.revision++;
        return json(draft);
      }
      if (pathname === draftPath && request.method() === "GET") return json(draft);
      if (pathname === draftPath && request.method() === "PUT") {
        const { expected_revision, idempotency_key, ...payload } = request.postDataJSON() as FreshPayload & { expected_revision: number; idempotency_key: string };
        expect(expected_revision).toBe(draft.revision);
        expect(idempotency_key.length).toBeGreaterThanOrEqual(16);
        Object.assign(draft, payload, { revision: draft.revision + 1 });
        return json(draft);
      }
    }
    if (pathname.endsWith("/telemetry")) return json({});
    unexpected.push(`${request.method()} ${pathname}`);
    return json({ error: { message: "Unexpected test request" } }, 400);
  });
  await page.goto(`/upload/${token}`);
  await page.getByRole("button", { name: /New traveller/ }).click();
  await page.getByRole("button", { name: "Only me", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Relation with Qualifier" })).toBeVisible();
  return { saves, errors, unexpected, drafts, qualifierReads };
}

for (const viewport of [{ width: 1440, height: 1100 }, { width: 390, height: 950 }, { width: 320, height: 950 }]) {
  for (const methods of [{ list: true, other: false }, { list: false, other: true }, { list: true, other: true }]) {
    test(`relationship methods list=${methods.list} other=${methods.other} at ${viewport.width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize(viewport);
      const fixture = await prepareLink(page, methods);
      const relationship = page.locator('section[aria-labelledby="qualifier-choice-title"]');
      await expect(relationship.getByRole("combobox")).toHaveCount(Number(methods.list));
      await expect(relationship.getByRole("textbox", { name: "Specify relationship" })).toHaveCount(Number(methods.other));
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
        await relationship.getByRole("textbox", { name: "Specify relationship" }).fill("  Cousin  ");
      } else await relationship.getByRole("combobox").selectOption("spouse");
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
  await expect(page.getByText("Qualifier relationship saved", { exact: true })).toBeVisible();
  await expect.poll(() => Array.from(fixture.drafts.values())[0]?.collection?.qualifier_selection_token).toBeTruthy();
  const originalProof = Array.from(fixture.drafts.values())[0].collection!.qualifier_selection_token;
  await page.reload();
  await page.getByRole("button", { name: /Continue from where you left/ }).click();
  await expect(page.getByText("Qualifier relationship saved", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Change", exact: true }).click();
  await expect(page.getByRole("radio", { name: /Other relationship/ })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("textbox", { name: "Specify relationship" })).toHaveValue("Cousin");
  expect(fixture.qualifierReads).toEqual([originalProof]);
  await page.getByRole("textbox", { name: "Specify relationship" }).fill("Colleague");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect.poll(() => fixture.saves.length).toBe(2);
  expect(fixture.saves[1]).toEqual({ is_self: false, relation_code: "other", other_relation: "Colleague" });
  await expect.poll(() => Array.from(fixture.drafts.values())[0]?.collection?.qualifier_selection_token).not.toBe(originalProof);
  expect(Array.from(fixture.drafts.values())[0].collection!.qualifier_selection_token).toBeTruthy();
  expect(fixture.errors).toEqual([]);
  expect(fixture.unexpected).toEqual([]);
});
