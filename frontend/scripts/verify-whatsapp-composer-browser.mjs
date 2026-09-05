/**
 * Local-only UI verification for the real /whatsapp message composers.
 * Start Next on loopback, then run:
 * node scripts/verify-whatsapp-composer-browser.mjs --url http://127.0.0.1:3186
 * Auth and message APIs use synthetic fixtures. No message can be sent.
 */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, expect } from "@playwright/test";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const urlIndex = process.argv.indexOf("--url");
const origin = new URL(urlIndex < 0 ? "http://127.0.0.1:3186" : process.argv[urlIndex + 1]);
assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname), "Only a loopback test server is allowed");
assert.ok(["http:", "https:"].includes(origin.protocol));
const output = join(frontend, "test-results", "whatsapp-composer-browser");
await mkdir(output, { recursive: true });

const group = {
  id: "composer-ui-verification",
  name: "Sample International Leadership Conference and Partner Recognition Programme — November 2026",
  recipient_count: 3,
  total_contact_count: 3,
  recipient_opt_in_confirmed: true,
  created_at: "2026-09-06T00:00:00Z",
  updated_at: "2026-09-06T00:00:00Z",
};
const recipients = [
  { id: "sample-recipient-a", name: "AlexandraSampleLongRecipientNameForResponsivePreviewVerification" },
  { id: "sample-recipient-b", name: "Jordan Sample" },
  { id: "sample-recipient-c", name: "Morgan Sample" },
].map((recipient, index) => ({
  ...recipient, phone_number: `+1202555010${index}`, normalized_phone_number: `+1202555010${index}`,
  imported_fields: {}, message_statuses: [],
}));
const detail = {
  ...group, recipients, rejected_contact_count: 0,
  support_contacts: [{ id: "sample-support", name: "InternationalTravelOperationsSupportDeskForEnterpriseDelegates", phone_number: "+12025550109", normalized_phone_number: "+12025550109" }],
};
const user = {
  id: "composer-test-admin", email: "admin@example.test", full_name: "Sample Agency Administrator",
  role: "agency_admin", agency_id: "sample-agency", is_active: true, last_login_at: null,
  created_at: group.created_at, updated_at: group.updated_at, capabilities: [],
};
const longLink = `https://travel.example.test/upload/${"sample-long-passport-link-".repeat(7)}`;
const scenarios = [
  { type: "welcome", action: "Send Welcome Message", title: "Preview Welcome Message", editor: "Welcome trip message" },
  { type: "passport_link", action: "Send Passport Link", title: "Preview Passport Link Message", editor: "Passport instructions" },
  { type: "reminder", action: "Send Reminder", title: "Preview Reminder", editor: "Reminder paragraph" },
];
const viewports = [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "mobile", width: 390, height: 844 },
];
const report = { origin: origin.origin, evidence: "Real local Next page; synthetic auth, recipients and preview responses; no provider calls", cases: [] };

function messagePreview(draft) {
  const recipient = recipients.find((candidate) => candidate.id === (draft.resend_recipient_id ?? draft.recipient_id)) ?? recipients[0];
  const selected = draft.recipient_ids === null || draft.recipient_ids === undefined
    ? recipients : recipients.filter((candidate) => draft.recipient_ids.includes(candidate.id));
  const intro = draft.passport_intro ?? "Please complete your travel document submission using the secure link below.";
  const content = draft.message_content ?? (draft.message_type === "reminder"
    ? "Please complete your outstanding travel details before the registration deadline. Our team is available if you need assistance."
    : `This message is regarding your upcoming trip to ${group.name}.`);
  const link = draft.passport_link ?? longLink;
  return {
    message_type: draft.message_type, template_name: `sample_${draft.message_type}_approved_v3`,
    recipient_id: recipient.id, recipient_name: recipient.name, recipient_count: recipients.length,
    eligible_recipient_count: selected.length, already_sent_count: 0, in_progress_count: 0, uncertain_recipient_count: 0,
    passport_intro: draft.message_type === "passport_link" ? intro : null,
    passport_link: draft.message_type === "passport_link" ? link : null,
    message_content: content, header_image_id: null, content_source: "default",
    rendered_message: `Dear ${recipient.name},\n\nGreetings from Global Connect Travels.\n\n${draft.message_type === "passport_link" ? `${intro}\n\n${link}\n\n` : ""}${content}\n\nThis is an automated notification sent individually to you. Replies to this WhatsApp message are not monitored.\n\nRegards,\nTeam Global Connect Travels`,
    header_parameter_values: [], parameter_values: [content],
  };
}

async function syntheticHeader(page) {
  const base64 = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 720; canvas.height = 450;
    const context = canvas.getContext("2d");
    context.fillStyle = "#173b59"; context.fillRect(0, 0, 720, 450);
    context.fillStyle = "#5eead4"; context.fillRect(54, 65, 64, 5);
    context.fillStyle = "#ffffff"; context.font = "bold 38px sans-serif";
    context.fillText("Welcome to your next journey", 54, 185, 612);
    context.font = "22px sans-serif"; context.fillStyle = "#cbd5e1";
    context.fillText("SAMPLE TRAVEL GROUP", 54, 242, 612);
    context.font = "16px sans-serif"; context.fillText("Illustrative local verification image", 54, 372, 612);
    return canvas.toDataURL("image/png").split(",")[1];
  });
  return { name: "sample-travel-header.png", mimeType: "image/png", buffer: Buffer.from(base64, "base64") };
}

async function verifyCase(browser, viewport, scenario) {
  const context = await browser.newContext({ viewport, serviceWorkers: "block" });
  const page = await context.newPage();
  page.setDefaultTimeout(25_000);
  const errors = [];
  const requests = [];
  const blocked = [];
  let previewCount = 0;
  const scenarioDetail = scenario.targetAction ? {
    ...detail,
    recipients: recipients.map((recipient, index) => ({
      ...recipient,
      message_statuses: index === 0 ? [{
        message_type: scenario.type, status: scenario.targetAction === "retry" ? "failed" : "sent",
        already_sent: scenario.targetAction === "resend", latest_resend_status: null,
        resend_blocked: false, submitted_at: group.updated_at, status_updated_at: group.updated_at,
      }] : [],
    })),
  } : detail;
  page.on("pageerror", (error) => errors.push(String(error)));
  await context.addCookies([{ name: "access_token", value: "synthetic-local-session", domain: origin.hostname, path: "/", httpOnly: true, sameSite: "Lax" }]);
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin.origin) {
      blocked.push(`${request.method()} ${request.url()}`);
      return route.abort("blockedbyclient");
    }
    if (!url.pathname.startsWith("/api/v1/")) return route.continue();
    requests.push(`${request.method()} ${url.pathname}`);
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname.endsWith("/send") || url.pathname.endsWith("/resend") || url.pathname.endsWith("/welcome-media")) {
      blocked.push(`${request.method()} ${url.pathname}`);
      return json({ error: { code: "LOCAL_TEST_SEND_BLOCKED", message: "Message sending is blocked by this local browser check." } }, 403);
    }
    if (url.pathname === "/api/v1/auth/me") return json(user);
    if (url.pathname === "/api/v1/auth/refresh") return json({ status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (url.pathname === "/api/v1/notifications/feed") return json({ items: [], unread_count: 0, next_cursor: null });
    if (url.pathname === "/api/v1/whatsapp/groups") return json([group]);
    if (url.pathname === `/api/v1/whatsapp/groups/${group.id}`) return json(scenarioDetail);
    if (url.pathname === `/api/v1/whatsapp/groups/${group.id}/recipient-roster`) return json({
      items: scenarioDetail.recipients.map((recipient, index) => ({ kind: "recipient", display_order: index + 1, recipient })),
      counts: { all: 3, sent: scenario.targetAction === "resend" ? 1 : 0, failed: scenario.targetAction === "retry" ? 1 : 0, rejected: 0, replaced: 0, unidentified: 0 },
    });
    if (url.pathname === `/api/v1/whatsapp/groups/${group.id}/preview`) {
      previewCount++;
      return json(messagePreview(request.postDataJSON()));
    }
    if (request.method() === "GET") return json([]);
    blocked.push(`${request.method()} ${url.pathname}`);
    return json({ error: { code: "LOCAL_TEST_UNEXPECTED_MUTATION", message: "Unexpected mutation blocked." } }, 403);
  });
  const caseName = `${viewport.name}-${scenario.type}${scenario.targetAction ? `-${scenario.targetAction}` : ""}`;
  const result = { viewport: viewport.name, messageType: scenario.type, ...(scenario.targetAction && { targetAction: scenario.targetAction }) };
  try {
    const response = await page.goto(`${origin.origin}/whatsapp`);
    assert.equal(response.status(), 200);
    const openActions = page.getByRole("button", { name: `Open actions for ${group.name}`, exact: true }).filter({ visible: true });
    await openActions.click();
    if (scenario.targetAction) await page.getByRole("button", { name: "Recipient List", exact: true }).click();
    await page.getByRole("button", { name: scenario.action, exact: true }).click();
    const dialog = page.getByRole("dialog", { name: scenario.title, exact: true });
    await expect(dialog).toBeVisible();
    const editor = dialog.getByLabel(scenario.editor, { exact: true });
    await expect(editor).not.toHaveValue("");
    const send = dialog.locator('button[type="submit"]');
    if (scenario.type !== "reminder") {
      await expect(send).toBeDisabled();
      result.missingImageBlocksSend = true;
      await dialog.locator('input[type="file"]').setInputFiles(await syntheticHeader(page));
    }
    await expect(send).toBeEnabled();
    if (scenario.targetAction) {
      const verb = scenario.targetAction === "retry" ? "Retry" : "Resend";
      await expect(send).toHaveAccessibleName(`${verb} to ${recipients[0].name}`);
      result.fullRecipientAccessibleName = true;
    }
    const currentContent = await editor.inputValue();
    await editor.fill(`${currentContent}\n\nPlease review your details carefully before your trip.`);
    await expect(send).toBeDisabled();
    await expect(send).toBeEnabled();
    result.editedPreviewBlocksStaleSend = true;
    if (scenario.type === "passport_link") {
      await expect(dialog.getByRole("textbox", { name: "Passport upload link", exact: true })).toHaveValue(longLink);
      await dialog.getByRole("radio", { name: "Custom select", exact: true }).check();
      await expect(send).toHaveText(/1/);
      await expect(send).toBeEnabled();
      await dialog.getByRole("radio", { name: "All unsent recipients", exact: true }).check();
      await expect(send).toHaveText(/3/);
      await expect(send).toBeEnabled();
      result.recipientSelectionVerified = true;
    }
    const preview = dialog.getByTestId("whatsapp-message-preview");
    await expect(preview).toBeVisible();
    const dimensions = await dialog.evaluate((element) => {
      const box = element.getBoundingClientRect();
      return {
        x: box.x, y: box.y, width: box.width, height: box.height,
        scrollWidth: element.scrollWidth, clientWidth: element.clientWidth,
        viewportWidth: innerWidth, viewportHeight: innerHeight,
        pageWidth: document.documentElement.scrollWidth,
      };
    });
    assert.ok(dimensions.x >= 0 && dimensions.x + dimensions.width <= viewport.width + 1, "Dialog stays within viewport width");
    assert.ok(dimensions.y >= 0 && dimensions.y + dimensions.height <= viewport.height + 1, "Dialog stays within viewport height");
    assert.ok(dimensions.scrollWidth <= dimensions.clientWidth + 1, "Dialog has no horizontal overflow");
    assert.ok(dimensions.pageWidth <= viewport.width, "Page has no horizontal overflow");
    const previewDimensions = await preview.evaluate((element) => ({ scrollWidth: element.scrollWidth, clientWidth: element.clientWidth }));
    assert.ok(previewDimensions.scrollWidth <= previewDimensions.clientWidth + 1, "Long recipient names and links wrap within preview");
    const footer = dialog.getByTestId("whatsapp-composer-footer");
    await expect(footer).toBeInViewport({ ratio: 1 });
    await dialog.evaluate((element) => {
      for (const child of element.querySelectorAll("*")) {
        if (child instanceof HTMLElement && child.scrollHeight > child.clientHeight) child.scrollTop = 0;
      }
    });
    const screenshot = join(output, `${caseName}.png`);
    await page.screenshot({ path: screenshot, animations: "disabled" });
    await preview.scrollIntoViewIfNeeded();
    await expect(footer).toBeInViewport({ ratio: 1 });
    await expect(send).toBeInViewport({ ratio: 1 });
    const previewScreenshot = join(output, `${caseName}-preview.png`);
    await page.screenshot({ path: previewScreenshot, animations: "disabled" });
    await send.focus();
    await page.keyboard.press("Tab");
    await expect(dialog.getByRole("button", { name: "Close dialog", exact: true })).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(send).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    if (!scenario.targetAction) await openActions.click();
    await page.getByRole("button", { name: scenario.action, exact: true }).click();
    const reopened = page.getByRole("dialog", { name: scenario.title, exact: true });
    await reopened.getByRole("button", { name: "Close dialog", exact: true }).click();
    await expect(reopened).toHaveCount(0);
    assert.deepEqual(errors, [], "No browser runtime errors");
    assert.deepEqual(blocked, [], "No outgoing messages or external requests attempted");
    Object.assign(result, { status: "passed", dimensions, previewDimensions, screenshot, previewScreenshot, previewCount, keyboardCloseVerified: true, footerVisible: true, requests });
    console.log(`PASS ${caseName}`);
    return result;
  } catch (error) {
    const screenshot = join(output, `${caseName}-failure.png`);
    await page.screenshot({ path: screenshot, animations: "disabled" }).catch(() => {});
    Object.assign(result, { status: "failed", error: String(error), errors, blocked, requests, screenshot, previewCount });
    throw Object.assign(error, { caseResult: result });
  } finally {
    await context.close();
  }
}

let browser;
try {
  browser = await chromium.launch({ headless: true });
  report.browser = browser.version();
  for (const viewport of viewports) {
    for (const scenario of scenarios) {
      report.cases.push(await verifyCase(browser, viewport, scenario));
    }
  }
  for (const targetAction of ["retry", "resend"]) {
    const verb = targetAction === "retry" ? "Retry" : "Resend";
    report.cases.push(await verifyCase(browser, viewports[1], {
      ...scenarios[0], targetAction,
      action: `${verb} Welcome message to ${recipients[0].name}`,
      title: `${verb} Welcome Message`,
    }));
  }
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.error = String(error);
  if (error.caseResult) report.cases.push(error.caseResult);
  console.error(error);
  process.exitCode = 1;
} finally {
  await browser?.close();
  await writeFile(join(output, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
}
