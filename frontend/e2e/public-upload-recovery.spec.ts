import { expect, test, type Page } from "@playwright/test";
import { DEFAULT_UPLOAD_CONFIGURATION } from "../features/passports/types/upload-configuration";
import { freshFields, freshPixel, freshStorageKey, mockFreshFlow, startFresh, verifyFreshContact } from "./support/public-fresh-flow";

const token = "public-recovery-token";
const passportGroup = { upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, passport_enabled: true, passport_required: true, passport_upload_pages: ["front"], passport_live_scan: false } };
const storedResume = (page: Page) => page.evaluate(key => localStorage.getItem(key), freshStorageKey(token));
const resume = async (page: Page) => { await page.reload(); await page.getByRole("button", { name: /Continue from where you left/ }).click(); };
const upload = async (page: Page, name = "synthetic.png") => {
  await page.getByLabel("Upload personal details page").setInputFiles({ name, mimeType: "image/png", buffer: freshPixel });
  await expect(page.getByLabel("Passport Number", { exact: true })).toHaveValue(freshFields.passport_number);
};

test("a deliberately closed link displays closed wording and can be checked after reopening", async ({ page }) => {
  const state = await mockFreshFlow(page, token);
  state.faults.closed = true;
  await page.goto(`/upload/${token}`);
  await expect(page.getByRole("heading", { name: "This link is closed." })).toBeVisible();
  await expect(page.getByRole("alert", { name: "This link is closed." })).not.toContainText("expired");
  expect(state.requests.filter(request => request.path === `/api/v1/upload-links/token/${token}`)).toHaveLength(1);
  expect(state.drafts.size).toBe(0);
  state.faults.closed = false;
  await page.getByRole("button", { name: "Check again" }).click();
  await expect(page.getByRole("button", { name: /New traveller/ })).toBeVisible();
  expect(state.requests.filter(request => request.path === `/api/v1/upload-links/token/${token}`)).toHaveLength(2);
  expect(state.unexpected).toEqual([]); expect(state.pageErrors).toEqual([]);
});

test("an expired server draft requires an explicit new start and never uploads automatically", async ({ page }) => {
  const state = await mockFreshFlow(page, token);
  await startFresh(page, token);
  const old = JSON.parse((await storedResume(page))!);
  state.faults.startStatus = 410;
  await resume(page);
  await expect(page.getByRole("alert").filter({ hasText: "private draft has expired" })).toBeVisible();
  expect(JSON.parse((await storedResume(page))!).fresh.members).toEqual(old.fresh.members);
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await page.getByRole("button", { name: /New traveller/ }).click();
  state.faults.startStatus = 0;
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByLabel("Full name", { exact: true })).toBeVisible();
  const next = JSON.parse((await storedResume(page))!);
  expect(next.fresh.members[0].sessionId).not.toBe(old.fresh.members[0].sessionId);
  expect(next.fresh.members[0].submissionKey).not.toBe(old.fresh.members[0].submissionKey);
  expect(state.requests.filter(request => request.method === "POST" && request.path.includes("/documents/"))).toEqual([]);
  expect(state.completions).toEqual([]); expect(state.unexpected).toEqual([]); expect(state.pageErrors).toEqual([]);
});

test("a link closed during private draft recovery retains its opaque resume credentials", async ({ page }) => {
  const state = await mockFreshFlow(page, token);
  await startFresh(page, token);
  const before = await storedResume(page);
  await page.reload();
  await expect(page.getByRole("button", { name: /Continue from where you left/ })).toBeVisible();
  state.faults.closed = true;
  await page.getByRole("button", { name: /Continue from where you left/ }).click();
  await expect(page.getByRole("alert").filter({ hasText: "This link is closed." })).toBeVisible();
  expect(await storedResume(page)).toBe(before);
  await page.reload();
  await expect(page.getByRole("heading", { name: "This link is closed." })).toBeVisible();
  expect(await storedResume(page)).toBe(before); expect(state.completions).toEqual([]);
  expect(state.unexpected).toEqual([]); expect(state.pageErrors).toEqual([]);
});

test("temporary recovery failure retains the private draft and retry restores the same session", async ({ page }) => {
  const state = await mockFreshFlow(page, token);
  await startFresh(page, token);
  await page.getByLabel("Full name", { exact: true }).fill("Asha Example");
  await verifyFreshContact(page);
  const before = await storedResume(page);
  state.faults.startStatus = 503;
  await resume(page);
  await expect(page.getByRole("alert").filter({ hasText: "temporarily unavailable" })).toBeVisible();
  expect(await storedResume(page)).toBe(before);
  state.faults.startStatus = 0;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByLabel("Full name", { exact: true })).toHaveValue("Asha Example");
  await expect(page.getByText("WhatsApp number verified", { exact: true })).toBeVisible();
  expect(state.drafts.size).toBe(1); expect(state.completions).toEqual([]);
  const sessions = new Set(state.requests.filter(request => request.path.includes("/public-drafts/")).map(request => request.session));
  expect(sessions.size).toBe(1); expect(state.unexpected).toEqual([]); expect(state.pageErrors).toEqual([]);
});

test("failed passport extraction blocks completion until a clear replacement succeeds", async ({ page }) => {
  const state = await mockFreshFlow(page, token, { group: passportGroup });
  state.faults.extraction = "failed";
  await startFresh(page, token); await upload(page); await verifyFreshContact(page);
  await expect(page.getByRole("alert").filter({ hasText: "couldn’t read this passport" })).toBeVisible();
  await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Wait for the passport check" })).toBeVisible();
  expect(state.completeAttempts).toEqual([]);
  state.faults.extraction = "succeeded";
  await upload(page, "synthetic-replacement.png");
  await expect(page.getByRole("alert").filter({ hasText: "couldn’t read this passport" })).toHaveCount(0);
  await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByRole("heading", { name: "You’re all set" })).toBeVisible();
  expect(state.completeAttempts).toHaveLength(1);
  expect(state.completeAttempts[0].body).not.toHaveProperty("manual_review_submission_allowed");
  expect(state.completeAttempts[0].draft.extraction_status).toBe("succeeded");
  expect(state.unexpected).toEqual([]); expect(state.pageErrors).toEqual([]);
});

test("resume retains private fields but discards images, and interrupted completion recovers one receipt", async ({ page }) => {
  const state = await mockFreshFlow(page, token, { group: passportGroup });
  await startFresh(page, token); await upload(page); await verifyFreshContact(page);
  const metadata = JSON.parse((await storedResume(page))!);
  const session = metadata.fresh.members[0].sessionId;
  expect(await storedResume(page)).not.toMatch(/TEST1234|Asha|Example|asha@example|9900001234|proof-|front-/);
  await resume(page);
  await expect(page.getByText("WhatsApp number verified", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Passport Number", { exact: true })).toHaveCount(0);
  expect(state.drafts.get(session)?.documents).toEqual([]);
  expect(state.drafts.get(session)?.passport_fields).toEqual(freshFields);
  expect(state.requests.filter(request => request.method === "POST" && request.path.includes("/documents/"))).toHaveLength(1);
  await upload(page, "synthetic-resumed.png");
  state.faults.interruptCompletion = true;
  await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByRole("button", { name: "Retry", exact: true })).toBeVisible();
  expect(state.completions).toEqual([session]);
  expect(state.completeAttempts[0].body.idempotency_key).toBe(metadata.fresh.members[0].submissionKey);
  await resume(page);
  await expect(page.getByRole("heading", { name: "Details submitted", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "You’re all set" })).toBeVisible();
  expect(await storedResume(page)).toBeNull();
  expect(state.drafts.size).toBe(1); expect(state.completeAttempts).toHaveLength(1); expect(state.completions).toEqual([session]);
  expect(state.unexpected).toEqual([]); expect(state.pageErrors).toEqual([]);
});
