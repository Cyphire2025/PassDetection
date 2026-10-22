import { createHash, randomUUID } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import type { FreshDraft } from "../features/upload/api/fresh-draft.api";
import { browserSeed, inspectPublishedUpload, installSyntheticOtpDelivery, syntheticCover } from "./workflow-support";

// External OTP delivery alone is captured; verification, uploads and completion
// use the real API. The separate scanner journey retains the real service worker.
test.use({ serviceWorkers: "block" });
const covers = [{ side: "cover", label: "front" }, { side: "back_cover", label: "back" }] as const;

async function uploadCovers(page: Page, path: string, session: string, content: Buffer) {
  const documents: Array<{ id: string; side: string; bytes: number; sha256: string }> = [];
  for (const { side, label } of covers) {
    const upload = page.waitForResponse((response) => new URL(response.url()).pathname === `${path}/documents/${side}` && response.request().method() === "POST");
    await page.getByLabel(`Upload passport ${label} cover`, { exact: true }).setInputFiles({ name: `synthetic-${side}.jpg`, mimeType: "image/jpeg", buffer: content });
    const response = await upload;
    expect(response.status()).toBe(200);
    expect(response.request().headers()["x-upload-session-id"]).toBe(session);
    const draft: FreshDraft = await response.json();
    const asset = draft.documents.find((item) => item.side === side)!;
    expect(asset).toMatchObject({ state: "ready" });
    const preview = await page.request.get(`${path}/documents/${asset.id}`, { headers: { "X-Upload-Session-ID": session } });
    expect(preview.status()).toBe(200);
    expect(preview.headers()["cache-control"]).toContain("private, no-store");
    expect(preview.headers()["content-type"]).toMatch(/^image\//);
    const bytes = await preview.body();
    expect(bytes.length).toBeGreaterThan(1000);
    documents.push({ id: asset.id, side, bytes: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex") });
  }
  return documents;
}

test("real fresh upload preserves private text and proof on reload, then publishes adopted documents exactly once", async ({ page }, info) => {
  test.setTimeout(120_000);
  const fixture = browserSeed().browser_workflows[info.project.name];
  const path = `/api/v1/public-drafts/${fixture.public_token}`;
  await page.setViewportSize({ width: 390, height: 844 });
  const deliveredCode = await installSyntheticOtpDelivery(page);
  const uploads: string[] = [], legacyRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url()).pathname;
    if (request.method() === "POST" && url.startsWith(`${path}/documents/`)) uploads.push(url);
    if (/\/passports\/upload\/|\/contact-otp\/|\/client-submit$/.test(url)) legacyRequests.push(url);
  });
  await page.goto(`/upload/${fixture.public_token}`);
  await page.getByRole("button", { name: /New traveller/ }).click();
  await page.getByRole("button", { name: "Only me", exact: true }).click();
  const started = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.request().method() === "POST");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  const start = await started;
  expect(start.status()).toBe(200);
  const draft: FreshDraft = await start.json();
  const session = start.request().headers()["x-upload-session-id"];
  expect(session).toMatch(/^[\da-f-]{36}$/i);
  const headers = { "X-Upload-Session-ID": session, Origin: new URL(page.url()).origin };
  const cookie = (await page.context().cookies()).find((value) => value.name === "pd_fresh_drafts");
  expect(cookie).toMatchObject({ httpOnly: true, secure: true, sameSite: "Strict", path: "/api/v1/public-drafts" });
  expect(await page.evaluate(() => document.cookie)).not.toContain("pd_fresh_drafts");
  await page.getByRole("textbox", { name: "Full name", exact: true }).fill("Synthetic Browser Traveller");
  const email = `synthetic.${draft.id}@example.com`;
  const phone = String(7_000_000_000 + Number.parseInt(draft.id.replaceAll("-", "").slice(0, 12), 16) % 1_000_000_000);
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(email);
  await page.getByRole("textbox", { name: "WhatsApp number", exact: true }).fill(phone);
  const cover = await syntheticCover(page);
  const temporary = await uploadCovers(page, path, session, cover);
  const wrongSession = await page.request.get(`${path}/documents/${temporary[0].id}`, { headers: { ...headers, "X-Upload-Session-ID": randomUUID() } });
  expect(wrongSession.status()).toBe(410);
  const wrongOrigin = await page.request.get(path, { headers: { ...headers, Origin: "https://untrusted.example" } });
  expect(wrongOrigin.status()).toBe(403);
  const requested = page.waitForResponse((response) => response.url().endsWith("/contact/request"));
  await page.getByRole("button", { name: "Verify WhatsApp number", exact: true }).click();
  const challenge = await (await requested).json();
  await expect(page.getByRole("textbox", { name: "Verification code", exact: true })).toBeVisible();
  const pendingDraft = await page.request.get(path, { headers });
  expect(pendingDraft.status()).toBe(200);
  const unverified = await page.request.post(`${path}/complete`, { headers, data: {
    expected_revision: (await pendingDraft.json()).revision, phone_verification_id: challenge.challenge_id,
    idempotency_key: randomUUID(), information_confirmed: true,
  } });
  expect(unverified.status()).toBe(403);
  const validCode = deliveredCode();
  const invalid = page.waitForResponse((response) => response.url().endsWith("/contact/verify"));
  await page.getByRole("textbox", { name: "Verification code", exact: true }).fill(validCode === "000000" ? "000001" : "000000");
  await page.getByRole("button", { name: "Confirm code", exact: true }).click();
  expect((await invalid).status()).toBe(403);
  await expect(page.getByText("WhatsApp number verified", { exact: true })).not.toBeAttached();
  const verified = page.waitForResponse((response) => response.url().endsWith("/contact/verify"));
  await page.getByRole("textbox", { name: "Verification code", exact: true }).fill(validCode);
  await page.getByRole("button", { name: "Confirm code", exact: true }).click();
  const verification = await verified;
  expect(verification.status()).toBe(200);
  const proof = await verification.json();
  await expect(page.getByText("WhatsApp number verified", { exact: true })).toBeVisible();
  const stored = await page.evaluate((key) => localStorage.getItem(key), `gc.traveller.draft.v1:${fixture.public_token}`);
  expect(stored).not.toBeNull();
  for (const personal of [email, phone, "Synthetic Browser Traveller", proof.phone_verification_id]) expect(stored).not.toContain(personal);

  // Current privacy contract: reopening retains encrypted text/contact proof,
  // but invalidates temporary image previews and asks for fresh image uploads.
  await page.reload();
  const resumed = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.request().method() === "POST");
  await page.getByRole("button", { name: /Continue from where you left/ }).click();
  const resumeResponse = await resumed;
  expect(resumeResponse.status()).toBe(200);
  const resumedDraft: FreshDraft = await resumeResponse.json();
  expect(resumedDraft).toMatchObject({ id: draft.id, documents: [], phone_verification_id: proof.phone_verification_id });
  await expect(page.getByRole("textbox", { name: "Full name", exact: true })).toHaveValue("Synthetic Browser Traveller");
  await expect(page.getByRole("textbox", { name: "Email", exact: true })).toHaveValue(email);
  await expect(page.getByRole("textbox", { name: "WhatsApp number", exact: true })).toHaveValue(phone);
  await expect(page.getByText("WhatsApp number verified", { exact: true })).toBeVisible();
  expect(uploads).toHaveLength(2);
  for (const asset of temporary) expect((await page.request.get(`${path}/documents/${asset.id}`, { headers })).status()).toBe(403);
  const adopted = await uploadCovers(page, path, session, cover);
  expect(uploads).toHaveLength(4);
  expect(adopted.every((asset) => temporary.every((old) => old.id !== asset.id))).toBe(true);
  const submit = page.waitForResponse((response) => response.url().endsWith(`${path}/complete`));
  await page.getByRole("button", { name: "Confirm details and submit", exact: true }).click();
  const submitted = await submit;
  expect(submitted.status()).toBe(200);
  const result = await submitted.json();
  expect(result.status).toBe("needs_review");
  await expect(page.getByRole("heading", { name: "You’re all set", exact: true })).toBeVisible();
  const replay = await page.request.post(`${path}/complete`, { headers, data: submitted.request().postDataJSON() });
  expect(replay.status()).toBe(200);
  expect(await replay.json()).toEqual(result);
  const evidence = await inspectPublishedUpload(page, fixture.public_token, session, result.source_submission_id);
  expect(evidence).toMatchObject({ source_submission_id: result.source_submission_id, source_status: "needs_review",
    source_count: 1, reviewed: true, upload_session_bound: true, draft_status: "submitted",
    draft_proof_status: "consumed", published_proof_status: "consumed", same_proof: true });
  expect(evidence.documents).toHaveLength(2);
  for (const asset of adopted) expect(evidence.documents).toContainEqual({ ...asset, state: "adopted", checksum_matches: true, legacy_temporary_key: false });
  expect(legacyRequests).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: info.outputPath("real-upload-complete.png"), fullPage: true });
});
