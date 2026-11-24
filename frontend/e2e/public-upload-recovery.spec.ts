import { expect, test } from "@playwright/test";
import { closedLink, enterFresh, expectFreshFixtureClean, fillFreshDetails, freshToken, mockFreshPublicUpload, readFreshResume, resumeFresh, seedFreshResume, uploadFreshPassport, verifyFreshContact } from "./support/fresh-public-upload";

test("a deliberately closed link displays closed wording and can be checked after reopening", async ({ page }) => {
  const state = await mockFreshPublicUpload(page); state.faults.linkClosed = true;
  await page.goto(`/upload/${freshToken}`);
  const failure = page.getByRole("alert", { name: "This link is closed." });
  await expect(failure).toBeVisible(); await expect(failure).not.toContainText("expired");
  expect(state.starts).toEqual([]); expect(state.uploads).toEqual([]);
  state.faults.linkClosed = false;
  await page.getByRole("button", { name: "Check again", exact: true }).click();
  await expect(page.getByRole("button", { name: /New traveller/ })).toBeVisible();
  expect(state.starts).toEqual([]); expectFreshFixtureClean(state);
});

test("a missing private draft starts empty without reading old data or uploading files", async ({ page }) => {
  const original = await seedFreshResume(page), state = await mockFreshPublicUpload(page);
  // The actual start endpoint creates an empty draft when the server row is gone.
  await resumeFresh(page);
  await expect(page.getByLabel("Full name", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("Base City", { exact: true })).toHaveValue("");
  expect(state.starts).toEqual([original.fresh.members[0].sessionId]);
  expect((await readFreshResume(page)).fresh).toEqual(original.fresh);
  expect(state.drafts.size).toBe(1); expect(state.uploads).toEqual([]); expect(state.completions).toEqual([]);
  expectFreshFixtureClean(state);
});

test("an expired private draft cannot restore data or upload files and can start fresh", async ({ page }) => {
  const original = await seedFreshResume(page), state = await mockFreshPublicUpload(page);
  const expired = { status: 410, code: "claim_expired", message: "Your secure session expired. Start again or submit fresh documents." };
  state.faults.start = expired;
  await resumeFresh(page);
  await expect(page.getByRole("alert").filter({ hasText: expired.message })).toBeVisible();
  expect(await readFreshResume(page)).toEqual(original);
  expect(state.drafts.size).toBe(0); expect(state.uploads).toEqual([]); expect(state.completions).toEqual([]);
  state.faults.start = undefined;
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await page.getByRole("button", { name: /New traveller/ }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByLabel("Full name", { exact: true })).toHaveValue("");
  const next = await readFreshResume(page);
  expect(next.fresh.members[0].sessionId).not.toBe(original.fresh.members[0].sessionId);
  expect(state.uploads).toEqual([]); expect(state.drafts.size).toBe(1); expectFreshFixtureClean(state);
});

test("a link closed during private recovery preserves the member credential for explicit retry", async ({ page }) => {
  const original = await seedFreshResume(page), state = await mockFreshPublicUpload(page);
  state.faults.start = closedLink;
  await resumeFresh(page);
  await expect(page.getByRole("alert").filter({ hasText: "This link is closed." })).toBeVisible();
  expect(await readFreshResume(page)).toEqual(original);
  expect(state.starts).toEqual([original.fresh.members[0].sessionId]);
  expect(state.uploads).toEqual([]);
  state.faults.start = undefined;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByLabel("Full name", { exact: true })).toBeVisible();
  expect(state.starts).toEqual([original.fresh.members[0].sessionId, original.fresh.members[0].sessionId]);
  expect((await readFreshResume(page)).fresh).toEqual(original.fresh);
  expectFreshFixtureClean(state);
});

test("a temporary private draft read failure retains the accepted image and retries without another upload", async ({ page }) => {
  const state = await mockFreshPublicUpload(page, { passport: true });
  state.faults.extractionPending = true; state.faults.read = true;
  await enterFresh(page); await fillFreshDetails(page); await uploadFreshPassport(page);
  await expect(page.getByLabel("Passport Number", { exact: true })).toHaveValue("TEST1234");
  const record = await readFreshResume(page), draft = [...state.drafts.values()][0];
  await expect(page.getByRole("alert").filter({ hasText: "Private draft is temporarily unavailable" })).toBeVisible();
  expect(await readFreshResume(page)).toEqual(record); expect(state.reads.length).toBeGreaterThan(0);
  state.faults.read = false; draft.extraction_status = "succeeded";
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Private draft is temporarily unavailable" })).toHaveCount(0);
  await verifyFreshContact(page); await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByRole("heading", { name: "You’re all set" })).toBeVisible();
  expect(state.uploads).toHaveLength(1); expect(state.acceptedUploadKeys.size).toBe(1);
  expect(state.completions).toHaveLength(1); expectFreshFixtureClean(state);
});

test("failed AI reading allows manual corrections but requires verified replacement before staff review", async ({ page }) => {
  const state = await mockFreshPublicUpload(page, { passport: true });
  state.faults.extractionFailed = true; state.faults.resultStatus = "needs_review";
  await enterFresh(page); await fillFreshDetails(page); await uploadFreshPassport(page);
  await expect(page.getByRole("alert").filter({ hasText: "couldn’t read this passport" })).toBeVisible();
  await page.getByLabel("Passport Number", { exact: true }).fill("MANUAL123");
  await verifyFreshContact(page); await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "passport check to finish" })).toBeVisible();
  expect(state.completionAttempts).toEqual([]);
  state.faults.extractionFailed = false;
  await uploadFreshPassport(page, "clearer-synthetic-passport.jpg");
  await expect(page.getByRole("alert").filter({ hasText: "couldn’t read this passport" })).toHaveCount(0);
  await expect(page.getByLabel("Passport Number", { exact: true })).toHaveValue("TEST1234");
  await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByRole("heading", { name: "You’re all set" })).toBeVisible();
  await expect(page.getByText("Your travel team will review them.", { exact: false })).toBeVisible();
  expect([...state.drafts.values()][0].result_status).toBe("needs_review");
  expect(state.completionAttempts).toHaveLength(1);
  expect(state.completionAttempts[0].body).not.toHaveProperty("manual_review_submission_allowed");
  expectFreshFixtureClean(state);
});

test("a lost document-upload response reconciles the accepted private image without uploading it twice", async ({ page }) => {
  const state = await mockFreshPublicUpload(page, { passport: true }); state.faults.interruptUploadOnce = true;
  await enterFresh(page); await fillFreshDetails(page);
  const record = await readFreshResume(page);
  await uploadFreshPassport(page);
  await expect.poll(() => state.acceptedUploadKeys.size).toBe(1);
  const failure = page.getByRole("alert").filter({ hasText: /Unable to reach the server/i });
  await expect(failure.first()).toBeVisible();
  expect((await readFreshResume(page)).fresh).toEqual(record.fresh);
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByLabel("Passport Number", { exact: true })).toHaveValue("TEST1234");
  await verifyFreshContact(page); await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByRole("heading", { name: "You’re all set" })).toBeVisible();
  expect(state.uploads).toHaveLength(1); expect(state.acceptedUploadKeys.size).toBe(1);
  expect(state.reads.length).toBeGreaterThan(0); expect(state.completions).toHaveLength(1);
  expectFreshFixtureClean(state);
});
