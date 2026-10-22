import { expect, test } from "@playwright/test";
import { DEFAULT_UPLOAD_CONFIGURATION } from "../features/passports/types/upload-configuration";
import { expectNoHorizontalOverflow } from "./support/public-contact-otp";
import { fillFreshContact, freshStorageKey, mockFreshFlow, startFresh, verifyFreshContact } from "./support/public-fresh-flow";

const token = "public-contact-otp-e2e";
const group = {
  base_city_enabled: true,
  custom_details: [{ id: "reference", label: "Booking reference", enabled: true, required: false }],
  upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, passport_enabled: false, passport_required: false, required_fields: { base_city: true } },
};

for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`only verified contact can submit the private review on ${viewport.name}`, async ({ page }, info) => {
    await page.setViewportSize(viewport);
    const state = await mockFreshFlow(page, token, { group });
    await startFresh(page, token);
    await page.getByLabel("Full name", { exact: true }).fill("Asha Example");
    await page.getByLabel("Base City", { exact: true }).fill("Mumbai");
    await page.getByLabel("Booking reference", { exact: true }).fill("BOOK-123");
    const submit = page.getByRole("button", { name: "Confirm details and submit", exact: true });
    await expect(submit).toBeDisabled();
    await fillFreshContact(page, "asha@example.test", "99000");
    await expect(page.getByRole("button", { name: "Verify WhatsApp number", exact: true })).toBeDisabled();
    await page.getByLabel("WhatsApp number", { exact: true }).fill("9900001234");
    await page.getByRole("button", { name: "Verify WhatsApp number", exact: true }).click();
    await expect(page.getByRole("button", { name: /Resend in/ })).toBeDisabled();
    await page.getByLabel("Verification code", { exact: true }).fill("000000");
    await page.getByRole("button", { name: "Confirm code", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Invalid or expired" })).toBeVisible();
    await expect(submit).toBeDisabled(); expect(state.completeAttempts).toHaveLength(0);
    await page.getByLabel("Verification code", { exact: true }).fill("123456");
    await page.getByRole("button", { name: "Confirm code", exact: true }).click();
    await expect(submit).toBeEnabled();
    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: info.outputPath(`contact-review-${viewport.name}.png`), fullPage: true });
    const stored = await page.evaluate(key => localStorage.getItem(key), freshStorageKey(token));
    expect(stored).not.toMatch(/Asha|Mumbai|BOOK-123|asha@example|9900001234|proof-|challenge-/);
    await submit.click();
    await expect(page.getByRole("heading", { name: "You’re all set" })).toBeVisible();
    expect(state.completeAttempts).toHaveLength(1);
    expect(state.completeAttempts[0].draft.current_details).toMatchObject({ client_email: "asha@example.test", base_city: "Mumbai" });
    expect(state.completeAttempts[0].draft.custom_detail_answers).toEqual({ reference: "BOOK-123" });
    const session = state.completeAttempts[0].session;
    expect(state.requests.filter(request => request.path.includes("/contact/")).every(request => request.session === session)).toBe(true);
    expect(state.completions).toEqual([session]); expect(state.unexpected).toEqual([]); expect(state.pageErrors).toEqual([]);
  });
}

test("failed OTP delivery keeps submission blocked and retry verifies the same draft", async ({ page }) => {
  const state = await mockFreshFlow(page, token);
  state.faults.deliveryFailure = true;
  await startFresh(page, token);
  await page.getByLabel("Full name", { exact: true }).fill("Asha Example");
  await fillFreshContact(page);
  await page.getByRole("button", { name: "Verify WhatsApp number", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "temporarily unavailable" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirm details and submit" })).toBeDisabled();
  state.faults.deliveryFailure = false;
  await verifyFreshContact(page);
  expect(state.drafts.size).toBe(1); expect(state.completeAttempts).toHaveLength(0);
  const attempts = state.requests.filter(request => request.path.endsWith("/contact/request"));
  expect(attempts).toHaveLength(2); expect(attempts[0].session).toBe(attempts[1].session);
  expect(state.unexpected).toEqual([]); expect(state.pageErrors).toEqual([]);
});

test("family members use separate contact proofs and resume skips the completed head", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const state = await mockFreshFlow(page, token, { group });
  await startFresh(page, token, true);
  await page.getByLabel("Full name", { exact: true }).fill("Asha Example");
  await page.getByRole("combobox", { name: "Gender", exact: true }).selectOption("Female");
  await page.getByLabel("Base City", { exact: true }).fill("Mumbai");
  await verifyFreshContact(page);
  await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByText("Family member 2 of 2", { exact: true })).toBeVisible();
  await expect(page.getByText("WhatsApp number verified", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Confirm details and submit" })).toBeDisabled();
  await page.getByLabel("Full name", { exact: true }).fill("Rahul Example");
  await page.getByRole("combobox", { name: "Gender", exact: true }).selectOption("Male");
  await page.getByRole("combobox", { name: "Relationship", exact: true }).selectOption("Spouse");
  await page.getByLabel("Base City", { exact: true }).fill("Delhi");
  await verifyFreshContact(page, "rahul@example.test", "9900005678");
  state.faults.interruptCompletion = true;
  await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByRole("button", { name: "Retry", exact: true })).toBeVisible();
  await page.reload(); await page.getByRole("button", { name: /Continue from where you left/ }).click();
  await expect(page.getByText("Family member 2 of 2", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Details submitted", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "You’re all set" })).toBeVisible();
  expect(state.completeAttempts).toHaveLength(2); expect(new Set(state.completions).size).toBe(2);
  const [head, member] = state.completeAttempts;
  expect(member.session).not.toBe(head.session); expect(member.body.phone_verification_id).not.toBe(head.body.phone_verification_id);
  expect(member.draft.collection).toMatchObject({ family_head_name: "Asha Example", family_head_email: "asha@example.test", family_head_phone: "9900001234" });
  expect(member.draft.current_details).toMatchObject({ client_email: "rahul@example.test", base_city: "Delhi" });
  expect(state.unexpected).toEqual([]); expect(state.pageErrors).toEqual([]);
});

test("expired proof blocks submission and re-verification preserves entered details", async ({ page }) => {
  const state = await mockFreshFlow(page, token, { group });
  state.faults.proofSeconds = 2;
  await startFresh(page, token);
  await page.getByLabel("Full name", { exact: true }).fill("Asha Example");
  await page.getByLabel("Base City", { exact: true }).fill("Mumbai");
  await page.getByLabel("Booking reference", { exact: true }).fill("PRESERVED-123");
  await verifyFreshContact(page);
  const previousProof = [...state.drafts.values()][0].phone_verification_id;
  await expect(page.getByText("WhatsApp number verified", { exact: true })).toHaveCount(0, { timeout: 5000 });
  await expect(page.getByRole("button", { name: "Confirm details and submit" })).toBeDisabled();
  expect(state.completeAttempts).toHaveLength(0);
  state.faults.proofSeconds = 3600;
  await verifyFreshContact(page);
  await expect(page.getByLabel("Base City", { exact: true })).toHaveValue("Mumbai");
  await expect(page.getByLabel("Booking reference", { exact: true })).toHaveValue("PRESERVED-123");
  await page.getByRole("button", { name: "Confirm details and submit" }).click();
  await expect(page.getByRole("heading", { name: "You’re all set" })).toBeVisible();
  expect(state.completeAttempts[0].body.phone_verification_id).not.toBe(previousProof);
  expect(state.unexpected).toEqual([]); expect(state.pageErrors).toEqual([]);
});
