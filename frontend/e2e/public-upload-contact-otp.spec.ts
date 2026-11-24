import { expect, test } from "@playwright/test";
import { expectNoHorizontalOverflow } from "./support/public-contact-otp";
import { enterFresh, expectFreshFixtureClean, fillFreshDetails, mockFreshPublicUpload, readFreshResume, verifyFreshContact } from "./support/fresh-public-upload";

for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`current private draft requires verified contact before submitting on ${viewport.name}`, async ({ page }, info) => {
    await page.setViewportSize(viewport);
    const state = await mockFreshPublicUpload(page);
    await enterFresh(page); await fillFreshDetails(page);
    const send = page.getByRole("button", { name: "Verify WhatsApp number", exact: true });
    const submit = page.getByRole("button", { name: "Confirm details and submit" });
    await expect(submit).toBeDisabled();
    await page.getByLabel("Email", { exact: true }).fill("asha@example.test");
    await page.getByLabel("WhatsApp number", { exact: true }).fill("99000");
    await expect(send).toBeDisabled();
    await page.getByLabel("WhatsApp number", { exact: true }).fill("9900001234");
    await send.click();
    await expect(page.getByRole("button", { name: /^Resend in/ })).toBeDisabled();
    await page.getByLabel("Verification code", { exact: true }).fill("000000");
    await page.getByRole("button", { name: "Confirm code", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Invalid or expired" })).toBeVisible();
    await expect(submit).toBeDisabled();
    await expect(page.getByLabel("Base City", { exact: true })).toHaveValue("Mumbai");
    await page.getByLabel("Verification code", { exact: true }).fill("123456");
    await page.getByRole("button", { name: "Confirm code", exact: true }).click();
    await expect(page.getByText("WhatsApp number verified", { exact: true })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: info.outputPath(`current-contact-${viewport.name}.png`), fullPage: true });
    await submit.click();
    await expect(page.getByRole("heading", { name: "Youâ€™re all set" })).toBeVisible();
    expect(state.completions).toHaveLength(1);
    expect([...state.drafts.values()][0].current_details).toMatchObject({ client_email: "asha@example.test", base_city: "Mumbai" });
    expect(state.contacts.every(request => request.member === state.starts[0])).toBe(true);
    expect(state.uploads).toEqual([]); expectFreshFixtureClean(state);
  });
}

test("failed OTP delivery preserves private details, blocks completion and can be retried", async ({ page }) => {
  const state = await mockFreshPublicUpload(page); state.faults.delivery = true;
  await enterFresh(page); await fillFreshDetails(page);
  await page.getByLabel("Email", { exact: true }).fill("asha@example.test");
  await page.getByLabel("WhatsApp number", { exact: true }).fill("9900001234");
  await page.getByRole("button", { name: "Verify WhatsApp number", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "temporarily unavailable" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirm details and submit" })).toBeDisabled();
  await expect(page.getByLabel("Booking reference", { exact: true })).toHaveValue("PRIVATE-BOOKING");
  expect(state.completionAttempts).toEqual([]);
  state.faults.delivery = false; await verifyFreshContact(page);
  await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByRole("heading", { name: "Youâ€™re all set" })).toBeVisible();
  expect(state.contacts.filter(request => request.kind === "request")).toHaveLength(2);
  expect(state.completions).toHaveLength(1); expectFreshFixtureClean(state);
});

test("family contact retry preserves the completed head and only retries the second member", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const state = await mockFreshPublicUpload(page);
  await enterFresh(page, true); await fillFreshDetails(page, { family: true, head: true });
  await verifyFreshContact(page); await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByText("Family member 2 of 2", { exact: true })).toBeVisible();
  await fillFreshDetails(page, { name: "Rahul Example", city: "Delhi", reference: "SECOND-PRIVATE", family: true });
  await verifyFreshContact(page, "rahul@example.test");
  const beforeRetry = await readFreshResume(page);
  state.faults.rejectProofOnce = true;
  await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Verify your WhatsApp number again" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Verify WhatsApp number", exact: true })).toBeVisible();
  await expect(page.getByLabel("Base City", { exact: true })).toHaveValue("Delhi");
  expect((await readFreshResume(page)).fresh).toEqual(beforeRetry.fresh);
  expect(beforeRetry.fresh.members[0].completed).toBe(true);
  await verifyFreshContact(page, "rahul@example.test");
  await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByRole("heading", { name: "Youâ€™re all set" })).toBeVisible();
  expect(state.completionAttempts.map(request => request.member)).toEqual([state.completions[0], state.completions[1], state.completions[1]]);
  expect(state.completions).toHaveLength(2);
  const requests = state.contacts.filter(request => request.kind === "request");
  expect(requests).toHaveLength(3); expect(requests[0].member).not.toBe(requests[1].member); expect(requests[1].member).toBe(requests[2].member);
  const second = state.drafts.get(state.completions[1])!;
  expect(second.current_details).toMatchObject({ client_email: "rahul@example.test", base_city: "Delhi" });
  expect(second.collection).toMatchObject({ family_head_name: "Asha Example", family_head_email: "asha@example.test" });
  await expectNoHorizontalOverflow(page); expectFreshFixtureClean(state);
});

test("server-expired contact proof permits re-verification without losing private details", async ({ page }) => {
  const state = await mockFreshPublicUpload(page);
  await enterFresh(page); await fillFreshDetails(page, { reference: "PRESERVED-123" }); await verifyFreshContact(page);
  const member = state.starts[0], before = await readFreshResume(page);
  state.faults.rejectProofOnce = true;
  await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Verify your WhatsApp number again" })).toBeVisible();
  await expect(page.getByText("WhatsApp number verified", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Confirm details and submit" })).toBeDisabled();
  await expect(page.getByLabel("Base City", { exact: true })).toHaveValue("Mumbai");
  await expect(page.getByLabel("Booking reference", { exact: true })).toHaveValue("PRESERVED-123");
  await verifyFreshContact(page); await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByRole("heading", { name: "Youâ€™re all set" })).toBeVisible();
  expect(state.completions).toEqual([member]); expect(state.completionAttempts).toHaveLength(2);
  // The backend rotates a proof in the same row; successful re-verification need not change its ID.
  expect(state.contacts.filter(request => request.kind === "verify")).toHaveLength(2);
  expect(state.completionAttempts[0].body.idempotency_key).toBe(state.completionAttempts[1].body.idempotency_key);
  expect(before.fresh.members[0].sessionId).toBe(member); expectFreshFixtureClean(state);
});
