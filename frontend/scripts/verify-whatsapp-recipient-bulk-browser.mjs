/** Current multi-recipient selection, source-specific history resend and uncertain recovery.
 * node scripts/verify-whatsapp-recipient-bulk-browser.mjs --url http://127.0.0.1:3186 [--case all|desktop|mobile|retry|filters]
 * Every API is synthetic and external/non-API writes are blocked. No provider calls.
 */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, expect } from "@playwright/test";
import { localOrigin, viewports, assertClean, assertNoOverflow, assertDialogBoundary, assertMessagePane, syntheticHeader } from "./browser-verification-local-fixture.mjs";
import { whatsappFixture, openComposer, catalog, groups, recipients, personalLink, savedMessage } from "./browser-verification-whatsapp-fixture.mjs";
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), ".."), origin = localOrigin();
const output = join(frontend, "test-results/whatsapp-recipient-bulk-browser"); await mkdir(output, { recursive: true });
const index = process.argv.indexOf("--case"), requested = index < 0 ? "all" : process.argv[index + 1];
assert.ok(["all", "desktop", "mobile", "retry", "filters"].includes(requested));
const report = { origin: origin.origin, evidence: "Current route-owned workspace; every API response synthetic; no provider calls", cases: [] };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
let browser;
async function verifyFilters(flow) {
  const { page, state } = flow;
  await page.goto(`${origin.origin}/whatsapp/${groups[0].id}/recipients`);
  await expect(page.getByRole("button", { name: /^All recipients/ })).toBeVisible();
  await page.getByRole("button", { name: /^Welcome failed/ }).click();
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(2);
  await expect(page.getByRole("table")).toContainText(recipients[2].name);
  await page.getByRole("button", { name: /^Contact issues/ }).click();
  await expect(page.getByRole("table")).toContainText("Rejected Synthetic");
  await expect(page.getByRole("checkbox", { name: /Rejected Synthetic/ })).toHaveCount(0);
  await page.goto(`${origin.origin}/whatsapp/${groups[0].id}/history?message=synthetic-passport`);
  const cases = [["All", 5], ["Sent", 1], ["Not sent", 1], ["Delivery left", 1], ["Failed", 3]];
  for (const [label, count] of cases) {
    await page.getByRole("button", { name: `${label} (${count})`, exact: true }).click();
    await expect(page.getByRole("table").getByRole("row")).toHaveCount(count + 1);
  }
  for (const person of [recipients[2], recipients[4]]) {
    const row = page.getByRole("row").filter({ hasText: person.name });
    await expect(row.getByRole("button", { name: "Resend", exact: true })).toBeDisabled();
  }
  await expect(page.getByText("Delivery is unconfirmed. Resending is paused to avoid duplicates.")).toHaveCount(2);
  await page.getByRole("searchbox", { name: "Search delivery recipients", exact: true }).fill("Bruno");
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(2);
  assert.equal(state.sends.length + state.resends.length, 0, "Filtering never sends a message");
  await assertNoOverflow(page); return true;
}
async function verifyHistorical(flow) {
  const { page, state } = flow;
  for (const type of ["welcome", "passport_link"]) {
    await page.goto(`${origin.origin}/whatsapp/${groups[0].id}/history?message=synthetic-${type === "welcome" ? "welcome" : "passport"}`);
    for (const [personIndex, action] of [[0, "Resend"], [1, "Retry"]]) {
      const person = recipients[personIndex], row = page.getByRole("row").filter({ hasText: person.name });
      await row.getByRole("button", { name: action, exact: true }).click();
      const dialog = page.getByRole("dialog", { name: `${action} this message`, exact: true });
      await expect(dialog).toContainText(savedMessage(person, type));
      await expect(dialog).not.toContainText(savedMessage(recipients[1 - personIndex], type));
      if (type === "passport_link") { await expect(dialog).toContainText(personalLink(person)); await expect(dialog).not.toContainText(personalLink(recipients[1 - personIndex])); }
      await expect(dialog.getByRole("textbox"), "Historical resends retain exact saved content rather than shared editable overrides").toHaveCount(0);
      await assertMessagePane(page, dialog.locator(".whitespace-pre-wrap"));
      await assertDialogBoundary(page, dialog);
      state.failResend = personIndex === 1; const before = state.resends.length;
      await dialog.getByRole("button", { name: "Send to this recipient", exact: true }).click();
      if (personIndex === 1) {
        await dialog.getByRole("button", { name: "Check resend status", exact: true }).click();
        await expect.poll(() => state.resends.length).toBe(before + 2);
        assert.deepEqual(state.resends[before], state.resends[before + 1], "Uncertain historical retry keeps the same source log, recipient and request ID");
      }
      await expect(dialog.getByRole("status")).toContainText("Send request recorded");
      const record = state.resends[before]; assert.equal(record.recipientId, person.id); assert.equal(record.groupId, groups[0].id);
      assert.equal(record.body.message_type, type); assert.equal(record.body.source_message_log_id, `saved-${type}-${person.id}`); assert.match(record.body.request_id, uuid);
      for (const key of ["passport_link", "message_content", "header_image_id", "recipient_ids"]) assert.equal(key in record.body, false, "Saved resend cannot leak a common content/link override");
      await dialog.getByRole("button", { name: "Done", exact: true }).click();
    }
  }
  assert.equal(state.media.length, 0, "Saved source resends do not upload images again");
}
async function verifyWorkspace(viewport) {
  const flow = await whatsappFixture(browser, origin, viewport), { page, state, diagnostics } = flow;
  const result = { name: `${viewport.name}-current-selection-history`, viewport: viewport.name }; report.cases.push(result);
  try {
    await verifyFilters(flow); await verifyHistorical(flow);
    await openComposer(page, origin, catalog[0]);
    const welcomeAudience = page.getByRole("region", { name: "Message audience" });
    await expect(welcomeAudience.getByRole("checkbox", { name: `Select ${recipients[0].name}`, exact: true })).toHaveCount(0);
    await expect(welcomeAudience.getByRole("checkbox", { name: `Select ${recipients[3].name}`, exact: true })).toHaveCount(0);
    await expect(welcomeAudience.getByRole("checkbox", { name: `Select ${recipients[2].name}`, exact: true })).toBeVisible();
    await openComposer(page, origin, catalog[1]);
    await page.getByRole("checkbox", { name: /Include people who received a previous passport link/ }).check();
    const audience = page.getByRole("region", { name: "Message audience" });
    await expect(audience.getByRole("checkbox", { name: /^Select / })).toHaveCount(2);
    for (const index of [2, 3, 4]) await expect(audience.getByRole("checkbox", { name: `Select ${recipients[index].name}`, exact: true })).toHaveCount(0);
    await audience.getByRole("button", { name: "Deselect matching", exact: true }).click();
    await audience.getByRole("checkbox", { name: `Select ${recipients[0].name}`, exact: true }).check();
    const search = audience.getByRole("searchbox", { name: "Search send recipients" });
    await search.fill("Bruno"); await expect(audience.getByRole("checkbox", { name: /^Select / })).toHaveCount(1);
    await audience.getByRole("button", { name: "Select all matching", exact: true }).click(); await search.fill("");
    await expect(audience.getByRole("checkbox", { name: /^Select / })).toHaveCount(2); for (const box of await audience.getByRole("checkbox", { name: /^Select / }).all()) await expect(box).toBeChecked();
    const editor = page.getByRole("textbox", { name: "Instructions", exact: true }), review = page.getByRole("button", { name: "Review message", exact: true });
    await page.getByLabel("Header image", { exact: true }).setInputFiles(await syntheticHeader(page));
    await expect(review).toBeEnabled(); await editor.fill(""); await expect(review).toBeDisabled();
    state.holdPreview = true; await editor.fill("Review your updated synthetic travel document instructions.");
    await expect.poll(() => Boolean(state.releasePreview)).toBe(true); await expect(review).toBeDisabled(); state.releasePreview(); await expect(review).toBeEnabled();
    await review.click(); let dialog = page.getByRole("dialog", { name: "Review and send", exact: true });
    await assertMessagePane(page, dialog.locator(".whitespace-pre-wrap"));
    await assertDialogBoundary(page, dialog); await page.keyboard.press("Escape"); await expect(dialog).toHaveCount(0);
    for (const box of await audience.getByRole("checkbox", { name: /^Select / }).all()) await expect(box).toBeChecked();
    await review.click(); dialog = page.getByRole("dialog", { name: "Review and send", exact: true }); state.holdSend = true;
    await dialog.getByRole("button", { name: "Send 2 messages", exact: true }).click(); await expect.poll(() => state.sends.length).toBe(1);
    await expect(dialog.getByRole("button").last()).toBeDisabled();
    await page.keyboard.press("Enter"); assert.equal(state.sends.length, 1, "Pending operation cannot submit twice");
    await page.keyboard.press("Escape"); await expect(dialog).toBeVisible();
    const record = state.sends[0]; assert.deepEqual([...record.body.recipient_ids].sort(), recipients.slice(0, 2).map(person => person.id).sort()); assert.match(record.key, uuid);
    assert.equal(record.body.include_previous_recipients, true); assert.equal(record.body.header_image_id, "synthetic-header");
    state.releaseSend(); await expect(page).toHaveURL(/history\?message=synthetic-batch-/);
    assert.equal(state.acceptedKeys.size, 1); assert.equal(state.media.length, 1);
    await expect.poll(() => page.evaluate(() => JSON.parse(sessionStorage.getItem("passdetection:whatsapp:tracked-activities:v1") ?? "[]").length)).toBe(1);
    const tracked = await page.evaluate(() => JSON.parse(sessionStorage.getItem("passdetection:whatsapp:tracked-activities:v1") ?? "[]"));
    assert.equal(tracked[0].sourceGroupId, groups[0].id); assert.equal(tracked[0].total, 2);
    await page.goto(`${origin.origin}/whatsapp/${groups[1].id}`); await page.getByRole("button", { name: /^Passport link Share secure/ }).click();
    await page.getByRole("checkbox", { name: /Include people who received a previous passport link/ }).check();
    await expect(page.getByRole("region", { name: "Message audience" })).toContainText("Other Group Passenger");
    for (const person of recipients) await expect(page.getByRole("checkbox", { name: `Select ${person.name}`, exact: true })).toHaveCount(0);
    const dimensions = await assertNoOverflow(page); assertClean(diagnostics);
    await page.screenshot({ path: join(output, `${viewport.name}-current-workspace.png`), fullPage: true });
    Object.assign(result, { passed: true, dimensions, savedRecipientIsolation: true, currentSelectionIsolation: true, pendingLock: true, exactSourceResends: state.resends.length });
  } catch (error) { Object.assign(result, { passed: false, failure: String(error), diagnostics }); await page.screenshot({ path: join(output, `${viewport.name}-failure.png`), fullPage: true }).catch(() => {}); throw error; }
  finally { state.releasePreview?.(); state.releaseSend?.(); await flow.context.close(); }
}
async function verifyUncertainRetry() {
  const flow = await whatsappFixture(browser, origin, viewports[0], { freshAudience: true }), { page, state, diagnostics } = flow;
  const result = { name: "uncertain-current-send-recovery" }; report.cases.push(result);
  try {
    await openComposer(page, origin, catalog[0]); await page.getByLabel("Header image", { exact: true }).setInputFiles(await syntheticHeader(page));
    const review = page.getByRole("button", { name: "Review message", exact: true }); await expect(review).toBeEnabled(); await review.click();
    let dialog = page.getByRole("dialog", { name: "Review and send" }); state.failSend = true;
    await dialog.getByRole("button", { name: "Send 3 messages", exact: true }).click();
    await expect.poll(() => state.sends.length).toBe(1); await expect(dialog.getByRole("alert")).toBeVisible();
    await dialog.getByRole("button", { name: "Back to editing", exact: true }).click();
    await page.getByRole("textbox", { name: "Welcome message", exact: true }).fill("A different current draft must not replace the earlier reviewed send.");
    await expect(page.getByRole("button", { name: "Refresh preview", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Check earlier send", exact: true }).click(); dialog = page.getByRole("dialog", { name: "Review and send" });
    await expect(dialog).not.toContainText("A different current draft");
    await dialog.getByRole("button", { name: "Check send status", exact: true }).click();
    await expect.poll(() => state.sends.length).toBe(2); await expect(page).toHaveURL(/history\?message=synthetic-batch-/);
    assert.deepEqual(state.sends[0], state.sends[1]); assert.equal(state.media.length, 1, "Recovery reuses the already uploaded media"); assert.equal(state.acceptedKeys.size, 1);
    const storage = await page.evaluate(() => Object.entries(sessionStorage).filter(([key]) => key.startsWith("passdetection:whatsapp-send:v1:")));
    assert.equal(storage.length, 1); assert.ok(!JSON.stringify(storage).includes("Please check"), "Recovery stores opaque hashes, not private message text");
    assertClean(diagnostics); Object.assign(result, { passed: true, exactPayloadRetry: true, retainedMedia: true, freshPreviewUnavailable: true });
  } catch (error) { Object.assign(result, { passed: false, failure: String(error), diagnostics }); await page.screenshot({ path: join(output, "uncertain-retry-failure.png"), fullPage: true }).catch(() => {}); throw error; }
  finally { await flow.context.close(); }
}
try {
  browser = await chromium.launch({ headless: true }); report.browser = browser.version();
  if (requested === "filters") for (const viewport of viewports) { const flow = await whatsappFixture(browser, origin, viewport); try { await verifyFilters(flow); assertClean(flow.diagnostics); report.cases.push({ name: `${viewport.name}-current-filters`, passed: true }); } finally { await flow.context.close(); } }
  for (const viewport of viewports.filter(item => requested === "all" || requested === item.name)) { await verifyWorkspace(viewport); console.log(`PASS ${viewport.name} current recipient/history workspace`); }
  if (["all", "retry"].includes(requested)) { await verifyUncertainRetry(); console.log("PASS current uncertain-send retry"); }
  report.passed = true;
} catch (error) { report.passed = false; report.failure = String(error); process.exitCode = 1; }
finally { await browser?.close(); await writeFile(join(output, "report.json"), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ passed: report.passed, failure: report.failure, cases: report.cases }, null, 2)); }
