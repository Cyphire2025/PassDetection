/** Current route-owned message library/composer, responsive preview and review gates.
 * node scripts/verify-whatsapp-composer-browser.mjs --url http://127.0.0.1:3186
 * All API traffic is synthetic; this verifier does not click a dispatch control.
 */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, expect } from "@playwright/test";
import { localOrigin, viewports, assertClean, assertNoOverflow, assertDialogBoundary, assertMessagePane, syntheticHeader } from "./browser-verification-local-fixture.mjs";
import { whatsappFixture, openComposer, catalog, longLink } from "./browser-verification-whatsapp-fixture.mjs";
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), ".."), origin = localOrigin();
const output = join(frontend, "test-results/whatsapp-composer-browser"); await mkdir(output, { recursive: true });
const report = { origin: origin.origin, evidence: "Current Next production routes; synthetic per-context APIs; no provider calls or dispatch clicks", cases: [] };
let browser;
try {
  browser = await chromium.launch({ headless: true }); report.browser = browser.version();
  for (const viewport of viewports) for (const definition of catalog) {
    const flow = await whatsappFixture(browser, origin, viewport, { freshAudience: true });
    const { page, state, people, diagnostics } = flow, result = { viewport: viewport.name, type: definition.id };
    report.cases.push(result);
    try {
      await openComposer(page, origin, definition);
      const editor = page.getByRole("textbox", { name: definition.fields.find(field => field.key === "message_content").label, exact: true });
      await expect(editor).not.toHaveValue("");
      const review = page.getByRole("button", { name: "Review message", exact: true });
      if (definition.image_required) {
        await expect(review).toBeDisabled(); result.missingImageBlocksSend = true;
        await page.getByLabel("Header image", { exact: true }).setInputFiles(await syntheticHeader(page));
      }
      await expect(review).toBeEnabled();
      const before = state.previews.length; state.holdPreview = true;
      await editor.fill(`${await editor.inputValue()}\nPlease review your details before departure.`);
      await expect.poll(() => Boolean(state.releasePreview)).toBe(true);
      await expect(review).toBeDisabled(); state.releasePreview();
      await expect(review).toBeEnabled(); assert.ok(state.previews.length > before); result.stalePreviewBlocksSend = true;
      if (definition.id === "passport_link") await expect(page.getByRole("textbox", { name: "Passport upload link", exact: true })).toHaveValue(longLink);
      const audience = page.getByRole("region", { name: "Message audience", exact: true });
      await audience.getByRole("button", { name: "Deselect matching", exact: true }).click();
      await expect(review).toBeDisabled();
      await audience.getByRole("checkbox", { name: `Select ${people[1].name}`, exact: true }).check();
      await expect(review).toBeEnabled();
      await expect(audience).toContainText("1 selected of 3 matching");
      const search = audience.getByRole("searchbox", { name: "Search send recipients", exact: true });
      await search.fill(people[2].name);
      await expect(audience.getByRole("checkbox", { name: /^Select / })).toHaveCount(1);
      await audience.getByRole("checkbox", { name: `Select ${people[2].name}`, exact: true }).check();
      await expect(review).toBeEnabled();
      await search.fill(""); await expect(audience.getByRole("checkbox", { name: /^Select / })).toHaveCount(3);
      await audience.getByRole("button", { name: "Select all matching", exact: true }).click();
      await expect(review).toBeEnabled(); result.recipientSelectionVerified = true;
      const preview = page.getByRole("region", { name: "WhatsApp message preview", exact: true });
      await expect(preview).toContainText(people[0].name); await assertNoOverflow(page, preview);
      const dimensions = await assertNoOverflow(page);
      await review.scrollIntoViewIfNeeded(); await expect(review).toBeInViewport({ ratio: 1 });
      await review.click(); const dialog = page.getByRole("dialog", { name: "Review and send", exact: true });
      await expect(dialog).toContainText("3 WhatsApp numbers"); await expect(dialog.getByRole("button", { name: "Send 3 messages", exact: true })).toBeEnabled();
      result.reviewTextBounds = await assertMessagePane(page, dialog.locator(".whitespace-pre-wrap"));
      await assertDialogBoundary(page, dialog); await page.keyboard.press("Escape"); await expect(dialog).toHaveCount(0);
      await review.click(); await page.getByRole("dialog").getByRole("button", { name: "Close dialog", exact: true }).click();
      await expect(page.getByRole("dialog")).toHaveCount(0);
      assert.equal(state.sends.length + state.resends.length + state.media.length, 0, "Preview/review cannot dispatch or upload header media"); assertClean(diagnostics);
      const screenshot = join(output, `${viewport.name}-${definition.id}.png`); await page.screenshot({ path: screenshot, fullPage: true });
      Object.assign(result, { status: "passed", dimensions, screenshot, keyboardBoundaryVerified: true, requests: diagnostics.requests });
      console.log(`PASS current composer ${viewport.name} ${definition.id}`);
    } catch (error) {
      Object.assign(result, { status: "failed", error: String(error), diagnostics });
      await page.screenshot({ path: join(output, `${viewport.name}-${definition.id}-failure.png`), fullPage: true }).catch(() => {}); throw error;
    } finally { state.releasePreview?.(); await flow.context.close(); }
  }
  report.passed = true;
} catch (error) { report.passed = false; report.failure = String(error); process.exitCode = 1; }
finally { await browser?.close(); await writeFile(join(output, "report.json"), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ passed: report.passed, failure: report.failure, cases: report.cases.length }, null, 2)); }
