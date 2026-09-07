/**
 * Real local /whatsapp UI, synthetic auth and recipient fixtures only.
 * node scripts/verify-whatsapp-recipient-bulk-browser.mjs --url http://127.0.0.1:3186
 * Every API request is intercepted. External requests and unexpected mutations
 * are blocked, so this check cannot deliver a message or modify production.
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
const output = join(frontend, "test-results", "whatsapp-recipient-bulk-browser");
await mkdir(output, { recursive: true });
const createdAt = "2026-09-07T00:00:00Z";
const groups = [{
  id: "bulk-qa-group-a", name: "Singapore Partner Conference — November 2026",
  recipient_count: 5, total_contact_count: 6, recipient_opt_in_confirmed: true,
  created_at: createdAt, updated_at: createdAt,
}, {
  id: "bulk-qa-group-b", name: "Sydney Leadership Conference",
  recipient_count: 1, total_contact_count: 1, recipient_opt_in_confirmed: true,
  created_at: createdAt, updated_at: createdAt,
}];
const user = {
  id: "bulk-qa-admin", email: "admin@example.test", full_name: "Sample Agency Administrator",
  role: "agency_admin", agency_id: "sample-agency", is_active: true, last_login_at: null,
  created_at: createdAt, updated_at: createdAt, capabilities: [],
};
function status(messageType, value = "sent") {
  return {
    message_type: messageType, status: value, already_sent: value === "sent",
    latest_resend_status: null, resend_blocked: value === "queued",
    submitted_at: createdAt, status_updated_at: createdAt,
  };
}
const recipients = [
  { id: "bulk-alex", name: "Alexandra Montgomery", message_statuses: [status("welcome"), status("passport_link")] },
  { id: "bulk-bruno", name: "Bruno Sample", message_statuses: [status("welcome"), status("passport_link")] },
  { id: "bulk-casey", name: "Casey Sample", message_statuses: [status("welcome", "failed"), status("passport_link", "failed")] },
  { id: "bulk-dana", name: "Dana Sample", message_statuses: [status("welcome", "queued"), status("passport_link")] },
  { id: "bulk-elliot", name: "Elliot Sample", message_statuses: [status("welcome")] },
].map((recipient, index) => ({
  ...recipient, phone_number: `+1202555010${index}`, normalized_phone_number: `+1202555010${index}`,
  imported_fields: { department: index < 2 ? "Operations" : "Coordination" },
}));
const secondRecipient = {
  ...recipients[0], id: "bulk-other-group", name: "Other Group Passenger", phone_number: "+12025550108", normalized_phone_number: "+12025550108",
};
const rejected = {
  id: "bulk-rejected", source_file_name: "synthetic-roster.xlsx", sheet_name: "Delegates", row_number: 7,
  raw_name: "Rejected Sample", raw_phone_number: "invalid", reason_code: "invalid_phone", reason: "This phone number is invalid.",
  created_at: createdAt, imported_fields: {},
};
const viewports = [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "mobile", width: 390, height: 844 },
];
const caseIndex = process.argv.indexOf("--case");
const requestedCase = caseIndex < 0 ? "all" : process.argv[caseIndex + 1];
assert.ok(["all", "desktop", "mobile", "retry"].includes(requestedCase), "--case must be all, desktop, mobile, or retry");
const report = {
  origin: origin.origin,
  evidence: "Real local Next page; every API response is synthetic; external requests and unexpected mutations are blocked; no WhatsApp provider calls",
  cases: [],
};

function detail(group) {
  return { ...group, recipients: group.id === groups[0].id ? recipients : [secondRecipient], support_contacts: [], rejected_contact_count: group.id === groups[0].id ? 1 : 0 };
}
function roster(group) {
  if (group.id === groups[1].id) return {
    items: [{ kind: "recipient", display_order: 1, recipient: secondRecipient }],
    counts: { all: 1, sent: 1, failed: 0, rejected: 0, replaced: 0, unidentified: 0 },
  };
  return {
    items: [...recipients.map((recipient, index) => ({ kind: "recipient", display_order: index + 1, recipient })), { kind: "rejected", display_order: 6, rejected_contact: rejected }],
    counts: { all: 6, sent: 4, failed: 1, rejected: 1, replaced: 0, unidentified: 0 },
  };
}
function responseFor(body, batchId) {
  const selected = recipients.filter((recipient) => body.recipient_ids.includes(recipient.id));
  const queued = selected.filter((recipient) => recipient.message_statuses.some((state) => state.message_type === body.message_type && state.status !== "queued"));
  const noSaved = selected.filter((recipient) => !recipient.message_statuses.some((state) => state.message_type === body.message_type));
  return {
    batch_id: batchId, selected: selected.length, queued: queued.length,
    sent: 0, failed: 0, delivery_unknown: 0, skipped_already_sent: 0,
    skipped_in_progress: selected.length - queued.length - noSaved.length,
    skipped_delivery_unknown: 0, skipped_no_saved_message: noSaved.length,
    skipped_replaced: 0, skipped_ineligible: 0, replayed: false,
    results: queued.map((recipient) => ({ recipient_id: recipient.id, phone_number: recipient.phone_number, status: "queued" })),
  };
}

async function createCase(browser, viewport, name) {
  const context = await browser.newContext({ viewport, serviceWorkers: "block" });
  const page = await context.newPage();
  page.setDefaultTimeout(25_000);
  const state = { errors: [], requests: [], blocked: [], bulkRequests: [], holdNext: false, failNext: false, release: null, activities: new Map() };
  page.on("pageerror", (error) => state.errors.push(String(error)));
  await context.addCookies([{ name: "access_token", value: "synthetic-local-session", domain: origin.hostname, path: "/", httpOnly: true, sameSite: "Lax" }]);
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin.origin) {
      state.blocked.push(`${request.method()} ${request.url()}`);
      return route.abort("blockedbyclient");
    }
    if (!url.pathname.startsWith("/api/")) {
      if (!["GET", "HEAD"].includes(request.method())) {
        state.blocked.push(`${request.method()} ${url.pathname}`);
        return route.abort("blockedbyclient");
      }
      return route.continue();
    }
    state.requests.push(`${request.method()} ${url.pathname}`);
    const json = (body, responseStatus = 200) => route.fulfill({ status: responseStatus, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === "/api/v1/auth/me") return json(user);
    if (url.pathname === "/api/v1/auth/refresh") return json({ status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (url.pathname === "/api/v1/notifications/feed") return json({ items: [], unread_count: 0, next_cursor: null });
    if (url.pathname === "/api/v1/whatsapp/groups") return json(groups);
    for (const group of groups) {
      if (url.pathname === `/api/v1/whatsapp/groups/${group.id}` && request.method() === "GET") return json(detail(group));
      if (url.pathname === `/api/v1/whatsapp/groups/${group.id}/recipient-roster` && request.method() === "GET") return json(roster(group));
    }
    if (url.pathname === `/api/v1/whatsapp/groups/${groups[0].id}/recipients/resend` && request.method() === "POST") {
      const body = request.postDataJSON();
      state.bulkRequests.push(body);
      if (state.failNext) { state.failNext = false; return route.abort("failed"); }
      if (state.holdNext) {
        state.holdNext = false;
        await new Promise((release) => { state.release = release; });
        state.release = null;
      }
      const batchId = `synthetic-bulk-batch-${state.bulkRequests.length}`;
      const result = responseFor(body, batchId);
      state.activities.set(batchId, {
        activity_id: batchId, kind: "broadcast", title: `${body.message_type === "welcome" ? "Welcome message" : "Passport link"} resend`,
        context_label: groups[0].name, source_group_id: groups[0].id, document_type: null,
        total: result.queued, queued: result.queued, sent: 0, failed: 0, delivery_unknown: 0,
        started_at: new Date().toISOString(), updated_at: new Date().toISOString(),
      });
      return json(result);
    }
    const activityId = url.pathname.match(/^\/api\/v1\/whatsapp\/activities\/broadcast\/([^/]+)$/)?.[1];
    if (activityId && state.activities.has(activityId)) return json(state.activities.get(activityId));
    if (request.method() === "GET") return json([]);
    state.blocked.push(`${request.method()} ${url.pathname}`);
    return json({ error: { code: "LOCAL_TEST_UNEXPECTED_MUTATION", message: "Unexpected mutation blocked by synthetic browser verification." } }, 403);
  });
  const result = { name, viewport: viewport.name };
  return { context, page, state, result };
}

async function openRecipients(page, group = groups[0]) {
  await page.getByRole("button", { name: `Open actions for ${group.name}`, exact: true }).filter({ visible: true }).click();
  await page.getByRole("button", { name: "Recipient List", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: `Recipients — ${group.name}`, exact: true });
  await expect(dialog).toBeVisible();
  return dialog;
}
function selectionActions(dialog) {
  return dialog.locator('[aria-label="Selected recipients"], [aria-label="Selected recipient actions"]').filter({ visible: true });
}
async function assertFit(dialog, viewport) {
  const dimensions = await dialog.evaluate((element) => {
    const box = element.getBoundingClientRect();
    return { x: box.x, y: box.y, width: box.width, height: box.height, scrollWidth: element.scrollWidth, clientWidth: element.clientWidth, pageWidth: document.documentElement.scrollWidth };
  });
  assert.ok(dimensions.x >= -1 && dimensions.x + dimensions.width <= viewport.width + 1, "Workspace stays within viewport width");
  assert.ok(dimensions.y >= -1 && dimensions.y + dimensions.height <= viewport.height + 1, "Workspace stays within viewport height");
  assert.ok(dimensions.scrollWidth <= dimensions.clientWidth + 1, "Workspace does not horizontally overflow");
  assert.ok(dimensions.pageWidth <= viewport.width + 1, "Page does not horizontally overflow");
  return dimensions;
}
async function review(page, dialog, type) {
  await selectionActions(dialog).getByRole("button", { name: type === "welcome" ? "Resend welcome" : "Resend passport link", exact: true }).click();
  const confirmation = page.getByRole("dialog", { name: type === "welcome" ? "Resend welcome message?" : "Resend passport link?", exact: true });
  await expect(confirmation).toBeVisible();
  return confirmation;
}
function assertPayload(body, type, ids) {
  assert.equal(body.message_type, type);
  assert.deepEqual([...body.recipient_ids].sort(), [...ids].sort(), "Only explicitly selected recipient IDs reach the bulk endpoint");
  assert.match(body.request_id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i, "Every operation has a UUID idempotency key");
}

async function verifyWorkspace(browser, viewport) {
  const fixture = await createCase(browser, viewport, `${viewport.name}-recipient-selection`);
  const { context, page, state, result } = fixture;
  try {
    const response = await page.goto(`${origin.origin}/whatsapp`);
    assert.equal(response.status(), 200);
    const dialog = await openRecipients(page);
    const actions = selectionActions(dialog);
    const search = dialog.getByRole("searchbox", { name: "Search current recipients", exact: true });
    await dialog.getByRole("checkbox", { name: `Select ${recipients[0].name}`, exact: true }).check();
    await search.fill("Bruno");
    await expect(dialog.getByRole("checkbox", { name: `Select ${recipients[0].name}`, exact: true })).toHaveCount(0);
    await dialog.getByRole("checkbox", { name: "Select all matching recipients", exact: true }).check();
    await expect(actions).toContainText(/2 selected|2 recipients/i);
    await search.fill("");
    await expect(dialog.getByRole("checkbox", { name: `Select ${recipients[0].name}`, exact: true })).toBeChecked();
    await expect(dialog.getByRole("checkbox", { name: `Select ${recipients[1].name}`, exact: true })).toBeChecked();
    await dialog.getByRole("tab", { name: /^Failed\b/ }).click();
    await expect(dialog.getByRole("checkbox", { name: `Select ${recipients[2].name}`, exact: true })).toBeVisible();
    await expect(actions).toContainText(/2 selected|2 recipients/i);
    await dialog.getByRole("tab", { name: /^All\b/ }).click();
    await expect(dialog.getByRole("checkbox", { name: "Select Rejected Sample", exact: true })).toHaveCount(0);
    result.selectionPersistsAcrossSearchAndStatus = true;
    result.rejectedRowsNotSelectable = true;
    result.dimensions = await assertFit(dialog, viewport);
    await page.screenshot({ path: join(output, `${viewport.name}-selected.png`), animations: "disabled" });

    let confirmation = await review(page, dialog, "welcome");
    await expect(page.getByRole("dialog")).toHaveCount(1);
    await expect(confirmation).toContainText(/2/);
    assert.equal(state.bulkRequests.length, 0, "Review does not send a message");
    result.confirmationDimensions = await assertFit(confirmation, viewport);
    await page.screenshot({ path: join(output, `${viewport.name}-review.png`), animations: "disabled" });
    await confirmation.getByRole("button", { name: "Confirm resend", exact: true }).focus();
    await page.keyboard.press("Tab");
    await expect(confirmation.getByRole("button", { name: "Close dialog", exact: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(1);
    await expect(dialog.getByRole("checkbox", { name: `Select ${recipients[0].name}`, exact: true })).toBeChecked();
    result.reviewFocusAndEscapeKeepWorkspaceSelection = true;
    confirmation = await review(page, dialog, "welcome");
    state.holdNext = true;
    await confirmation.getByRole("button", { name: "Confirm resend", exact: true }).click();
    await expect.poll(() => state.bulkRequests.length).toBe(1);
    await expect(confirmation.getByRole("button", { name: "Confirm resend", exact: true })).toBeDisabled();
    await page.keyboard.press("Enter");
    assert.equal(state.bulkRequests.length, 1, "A pending operation cannot submit twice");
    assertPayload(state.bulkRequests[0], "welcome", [recipients[0].id, recipients[1].id]);
    state.release();
    await expect(confirmation).toHaveCount(0);
    await expect(actions).toContainText(/2 selected|2 recipients/i);
    result.confirmationAndPendingLockVerified = true;

    const passportReview = await review(page, dialog, "passport_link");
    await passportReview.getByRole("button", { name: "Confirm resend", exact: true }).click();
    await expect.poll(() => state.bulkRequests.length).toBe(2);
    await expect(passportReview).toHaveCount(0);
    assertPayload(state.bulkRequests[1], "passport_link", [recipients[0].id, recipients[1].id]);
    assert.notEqual(state.bulkRequests[0].request_id, state.bulkRequests[1].request_id, "Different operations have different request IDs");
    result.bothMessageTypesUseExplicitSelection = true;
    await expect.poll(async () => page.evaluate(() => JSON.parse(sessionStorage.getItem("passdetection:whatsapp:tracked-activities:v1") ?? "[]").length)).toBe(2);
    const tracked = await page.evaluate(() => JSON.parse(sessionStorage.getItem("passdetection:whatsapp:tracked-activities:v1") ?? "[]"));
    assert.deepEqual(tracked.map((activity) => activity.id).sort(), ["synthetic-bulk-batch-1", "synthetic-bulk-batch-2"]);
    assert.ok(tracked.every((activity) => activity.total === 2 && activity.sourceGroupId === groups[0].id));
    result.batchesRegisteredWithGlobalActivityTracker = true;

    await actions.getByRole("button", { name: "Clear selection", exact: true }).click();
    await actions.getByRole("button", { name: "Select all 5 broadcast recipients", exact: true }).click();
    for (const recipient of recipients) await expect(dialog.getByRole("checkbox", { name: `Select ${recipient.name}`, exact: true })).toBeChecked();
    await expect(actions).toContainText(/5 selected|5 recipients/i);
    const allReview = await review(page, dialog, "welcome");
    await expect(allReview).toContainText(/skip|progress|pending|unavailable/i);
    await allReview.getByRole("button", { name: "Back to recipients", exact: true }).click();
    result.allBroadcastAndInProgressReviewVerified = true;

    const navigation = dialog.getByRole("navigation", { name: "Broadcast workspace", exact: true });
    await navigation.getByRole("button", { name: /^Add recipients\b/ }).click();
    await expect(dialog.getByRole("textbox", { name: /^Name$/ })).toBeVisible();
    await expect(dialog.getByRole("checkbox", { name: "Select all matching recipients", exact: true })).toHaveCount(0);
    await page.screenshot({ path: join(output, `${viewport.name}-add-recipients.png`), animations: "disabled" });
    await navigation.getByRole("button", { name: /^Broadcast details\b/ }).click();
    await expect(dialog.getByRole("textbox", { name: /Broadcast name|Group name/ })).toBeVisible();
    await navigation.getByRole("button", { name: /^Recipients\b/ }).click();
    await expect(selectionActions(dialog)).toContainText(/5 selected|5 recipients/i);
    result.sectionsSeparateFormsFromRoster = true;

    await dialog.getByLabel(`Actions for ${recipients[4].name}`, { exact: true }).click();
    const removeLastRecipient = dialog.getByRole("button", { name: `Remove ${recipients[4].name} from broadcast`, exact: true });
    await expect(removeLastRecipient).toBeInViewport({ ratio: 1 });
    await expect(dialog.getByRole("button", { name: `Resend Welcome message to ${recipients[4].name}`, exact: true })).toBeInViewport({ ratio: 1 });
    await page.screenshot({ path: join(output, `${viewport.name}-last-row-actions.png`), animations: "disabled" });
    await removeLastRecipient.focus();
    result.menuBeforeEscape = await removeLastRecipient.evaluate((element) => ({ open: element.closest("details")?.open, focused: element === document.activeElement, activeTag: document.activeElement?.tagName }));
    await expect(removeLastRecipient).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    await expect(removeLastRecipient).not.toBeVisible();
    result.lastRowActionsVisibleAndEscapeScoped = true;

    await dialog.getByRole("button", { name: "Close dialog", exact: true }).click();
    const secondDialog = await openRecipients(page, groups[1]);
    await expect(secondDialog.getByRole("checkbox", { name: `Select ${secondRecipient.name}`, exact: true })).not.toBeChecked();
    await expect(selectionActions(secondDialog).getByRole("button", { name: "Resend welcome", exact: true })).toBeDisabled();
    result.selectionDoesNotLeakToAnotherBroadcast = true;
    assert.deepEqual(state.errors, [], "No browser runtime errors");
    assert.deepEqual(state.blocked, [], "No unexpected mutations or external requests attempted");
    return { ...result, status: "passed", bulkRequests: state.bulkRequests, requests: state.requests };
  } catch (error) {
    await page.screenshot({ path: join(output, `${viewport.name}-failure.png`), animations: "disabled" }).catch(() => {});
    throw Object.assign(error, { caseResult: { ...result, status: "failed", error: String(error), errors: state.errors, blocked: state.blocked, requests: state.requests, bulkRequests: state.bulkRequests } });
  } finally {
    state.release?.();
    await context.close();
  }
}

async function verifyUncertainRetry(browser) {
  const fixture = await createCase(browser, viewports[0], "uncertain-request-retry");
  const { context, page, state, result } = fixture;
  try {
    await page.goto(`${origin.origin}/whatsapp`);
    const dialog = await openRecipients(page);
    await dialog.getByRole("checkbox", { name: `Select ${recipients[0].name}`, exact: true }).check();
    const confirmation = await review(page, dialog, "welcome");
    state.failNext = true;
    await confirmation.getByRole("button", { name: "Confirm resend", exact: true }).click();
    await expect.poll(() => state.bulkRequests.length).toBe(1);
    await expect(confirmation.getByRole("alert")).toBeVisible();
    await confirmation.getByRole("button", { name: "Confirm resend", exact: true }).click();
    await expect.poll(() => state.bulkRequests.length).toBe(2);
    await expect(confirmation).toHaveCount(0);
    assertPayload(state.bulkRequests[0], "welcome", [recipients[0].id]);
    assert.deepEqual(state.bulkRequests[0], state.bulkRequests[1], "Retry after an uncertain network response reuses the exact operation and request ID");
    assert.deepEqual(state.errors, []);
    assert.deepEqual(state.blocked, []);
    return { ...result, status: "passed", sameRequestIdOnRetry: true, bulkRequests: state.bulkRequests };
  } catch (error) {
    await page.screenshot({ path: join(output, "uncertain-retry-failure.png"), animations: "disabled" }).catch(() => {});
    throw Object.assign(error, { caseResult: { ...result, status: "failed", error: String(error), errors: state.errors, requests: state.requests, bulkRequests: state.bulkRequests } });
  } finally { await context.close(); }
}

let browser;
try {
  browser = await chromium.launch({ headless: true });
  report.browser = browser.version();
  for (const viewport of viewports.filter((candidate) => requestedCase === "all" || candidate.name === requestedCase)) {
    report.cases.push(await verifyWorkspace(browser, viewport));
    console.log(`PASS ${viewport.name} recipient workspace`);
  }
  if (requestedCase === "all" || requestedCase === "retry") {
    report.cases.push(await verifyUncertainRetry(browser));
    console.log("PASS uncertain response retry");
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
