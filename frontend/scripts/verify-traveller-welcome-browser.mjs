/** Local browser coverage with synthetic API fixtures. No provider or production access. */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, expect } from "@playwright/test";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const origin = new URL(process.argv[2] ?? "http://127.0.0.1:3188");
assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname));
const output = join(root, "test-results", "traveller-welcome-browser");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const report = { evidence: "Local Next app with synthetic API fixtures; no production or provider access", cases: [] };
const trip = "11111111-1111-4111-8111-111111111111";
const base = `/api/v1/document-distribution/groups/${trip}`;
const people = [
  { id: "mother", name: "Meera Sharma", phone: "+919900000001", welcomed: false },
  { id: "father", name: "Rajesh Sharma", phone: "+919900000002", welcomed: false },
  { id: "self", name: "Aarav Patel", phone: "+919900000003", welcomed: true },
];
const user = { id: "manager", full_name: "Travel Manager", email: "manager@example.test", role: "agency_manager", actual_role: "agency_manager", agency_id: "agency", is_active: true, capabilities: [], can_switch_access_level: false, created_at: "2026-09-12T00:00:00Z", updated_at: "2026-09-12T00:00:00Z" };

async function fixture(viewport) {
  const context = await browser.newContext({ viewport, serviceWorkers: "block" });
  const messages = [];
  const errors = [];
  let state = "required";
  const welcomed = (person) => person.welcomed || state === "delivered";
  await context.addCookies([{ name: "access_token", value: "synthetic-local-session", domain: origin.hostname, path: "/", httpOnly: true }]);
  await context.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin.origin) return route.abort("blockedbyclient");
    if (!url.pathname.startsWith("/api/v1/")) return route.continue();
    const json = (data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (url.pathname === "/api/v1/auth/me") return json(user);
    if (url.pathname === "/api/v1/auth/refresh") return json({ status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (url.pathname === "/api/v1/notifications/feed") return json({ items: [], unread_count: 0, next_cursor: null });
    if (url.pathname === "/api/v1/document-distribution/groups") return json([{ group_id: trip, group_name: "Company Singapore Trip", group_status: "active", destination: "Singapore", travel_date: "2026-10-15", total_passengers: 3, visa_assigned_count: 3, flight_ticket_assigned_count: 0, flight_ticket_arrival_assigned_count: 0, flight_ticket_domestic_assigned_count: 0, flight_ticket_domestic_arrival_assigned_count: 0, other_assigned_count: 0 }]);
    if (url.pathname === `${base}/visa`) return json({ batch_id: "batch", group_id: trip, document_type: "visa", status: "saved", uploaded_count: 3, rejected_count: 0, matched_count: 3, physical_file_count: 3, assigned_file_count: 3, assigned_passenger_count: 3, needs_assignment_count: 0, processing_upload_ids: [], saved_at: "2026-09-12T00:00:00Z", created_at: "2026-09-12T00:00:00Z", review_rows: people.map((person) => { const document = { id: `visa-${person.id}`, original_filename: `${person.id}-visa.pdf`, document_type: "visa", detected_type: "visa", match_status: "matched", match_confidence: 1, match_reason: null, extracted_name: person.name, extracted_passport_number: "SAMPLE", extracted_reference: null, source: "manual", delivery_status: "not_sent", sent_to: null, last_sent_at: null, can_resend: false, url: null }; return { passenger_id: person.id, passenger_name: person.name, passport_number: "SAMPLE", departure_city: "Delhi", document, documents: [document] }; }), unmatched_documents: [], assignment_issues: [], rejected_documents: [] });
    if (url.pathname === `${base}/whatsapp-welcome-preview`) return json({ group_id: trip, preview_token: "a".repeat(64), source_broadcast_id: "source", source_broadcast_name: "Company qualifiers", sources: [{ id: "source", name: "Company qualifiers" }], template_name: "welcome_v1", template_configured: true, can_send: state === "required", configuration_error: null, header_image_url: null, summary: { total_numbers: 3, needs_welcome: state === "required" ? 2 : 0, already_welcomed: state === "delivered" ? 3 : 1, in_progress: state === "queued" ? 2 : 0, blocked: 0 }, recipients: people.map((person) => ({ phone_number: person.phone, passenger_ids: [person.id], passenger_names: [person.name], status: welcomed(person) ? "delivered" : state, eligible: !welcomed(person) && state === "required", reason: welcomed(person) ? "Welcome was already delivered to this number." : state === "queued" ? "Waiting for welcome delivery confirmation." : "Welcome is required before private documents.", rendered_message: `Dear ${person.name},\n\nWelcome to your Singapore journey!\n\nOur Global Connect Travels team is here to help you prepare for your trip.\n\nRegards,\nTeam Global Connect Travels` })), poll_after_seconds: state === "queued" ? 5 : null });
    if (url.pathname === `${base}/whatsapp-welcome-send` && request.method() === "POST") {
      const body = request.postDataJSON();
      assert.deepEqual(body.phone_numbers.sort(), [people[0].phone, people[1].phone]);
      assert.equal(body.preview_token, "a".repeat(64));
      assert.equal(body.source_broadcast_id, "source");
      messages.push({ type: "welcome", body }); state = "queued";
      return json({ group_id: trip, batch_id: "welcome-batch", queued_count: 2, skipped_count: 1, blocked_count: 0, message: "2 traveller welcomes queued. Documents unlock after confirmed delivery." });
    }
    if (url.pathname === `${base}/visa/whatsapp-preview`) return json({ group_id: trip, batch_id: "batch", document_type: "visa", template_name: "documents_v1", template_configured: true, linked_broadcast_count: 1, can_send: true, configuration_error: null, message_content_1: "Please find your visa attached.", message_content_2: "Check your travel details and contact our team if you need help.", summary: { total_passengers: 3, ready: state === "delivered" ? 3 : 1, retryable: 0, already_sent: 0, in_progress: 0, blocked: state === "delivered" ? 0 : 2, welcome_required: state === "delivered" ? 0 : 2 }, recipients: people.map((person) => ({ passenger_id: person.id, passenger_name: person.name, passport_number: "SAMPLE", document_id: `visa-${person.id}`, document_filename: `${person.id}-visa.pdf`, document_type: "visa", recipient_id: null, broadcast_group_id: "source", broadcast_name: "Company qualifiers", phone_number: person.phone, phone_source: "submission", welcome_status: welcomed(person) ? "delivered" : state, welcome_required: !welcomed(person), delivery_id: null, delivery_status: welcomed(person) ? "ready" : "blocked", eligible: welcomed(person), resend_allowed: false, reason: welcomed(person) ? "Ready to deliver to this traveller." : "A welcome must be delivered to this traveller number first.", error_message: null, message_preview: null })) });
    if (request.method() === "GET") return json([]);
    errors.push(`Unexpected mutation: ${request.method()} ${url.pathname}`);
    return json({ detail: "This local test blocks unplanned mutations" }, 403);
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(String(error)));
  return { context, page, messages, errors, deliverWelcomes: () => { state = "delivered"; } };
}

try {
  for (const [name, viewport] of [["desktop", { width: 1440, height: 1000 }], ["mobile", { width: 390, height: 844 }]]) {
    const test = await fixture(viewport);
    const { page } = test;
    await page.goto(`${origin.origin}/documents/distribution/visa/${trip}`);
    await expect(page.getByRole("heading", { name: "Welcome travellers before sending documents" })).toBeVisible();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: join(output, `${name}-workspace.png`), fullPage: true });
    await page.getByRole("button", { name: "Send WhatsApp Broadcast" }).click();
    await expect(page.getByRole("dialog", { name: "Preview WhatsApp document delivery" })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "Send document to Meera Sharma" })).toBeDisabled();
    await expect(page.getByRole("checkbox", { name: "Send document to Aarav Patel" })).toBeChecked();
    await page.getByRole("button", { name: "Review traveller welcomes" }).last().click();
    await expect(page.getByRole("dialog", { name: "Welcome new traveller numbers" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Send welcome to 2 numbers" })).toBeEnabled();
    await expect(page.getByRole("checkbox", { name: `Welcome ${people[2].phone}` })).toBeDisabled();
    await page.screenshot({ path: join(output, `${name}-welcome-review.png`) });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.getByRole("button", { name: "Send welcome to 2 numbers" }).click();
    await expect(page.getByText("2 traveller welcomes queued. Documents unlock after confirmed delivery.")).toBeVisible();
    assert.equal(test.messages.length, 1);
    await page.getByRole("button", { name: "Send WhatsApp Broadcast" }).click();
    await expect(page.getByRole("checkbox", { name: "Send document to Meera Sharma" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Send individually to 1" })).toBeEnabled();
    await page.screenshot({ path: join(output, `${name}-documents-blocked.png`) });
    test.deliverWelcomes();
    await expect(page.getByRole("checkbox", { name: "Send document to Meera Sharma" })).toBeEnabled({ timeout: 12_000 });
    await expect(page.getByRole("button", { name: "Send individually to 3" })).toBeEnabled();
    await page.screenshot({ path: join(output, `${name}-documents-ready.png`) });
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await page.getByRole("button", { name: "Review traveller welcomes" }).click();
    await expect(page.getByRole("button", { name: "Send welcome to 0 numbers" })).toBeDisabled();
    assert.equal(test.messages.length, 1, "Already welcomed numbers must never requeue");
    assert.deepEqual(test.errors, []);
    report.cases.push(`${name}: original recipient skips welcome; parents' new numbers require welcome; submitted document destinations remain blocked while queued; confirmed delivery unlocks documents; no duplicate welcome`);
    await test.context.close();
  }
  await writeFile(join(output, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify(report, null, 2));
} finally { await browser.close(); }
