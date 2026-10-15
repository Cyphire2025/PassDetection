import { expect, test, type Page } from "@playwright/test";
import type { DocumentBatchReview, DistributedDocument } from "../types/document-distribution.types";
import type { WhatsAppBroadcastGroupDetail } from "../features/whatsapp/api/whatsapp.api";

const groupId = "document-client-group";
const broadcastId = "document-broadcast";
const timestamp = "2026-10-16T00:00:00Z";
const names = ["Waiting Traveller", "Shared Traveller", "Confirmed Traveller", "Other broadcast passenger"];
const document = (id: string, status = "not_sent"): DistributedDocument => ({ id, updated_at: timestamp, original_filename: "shared.pdf", document_type: "visa", detected_type: "visa", match_status: "matched", match_confidence: .97, match_reason: null, extracted_name: null, extracted_passport_number: null, extracted_reference: null, source: "manual", delivery_status: status, sent_to: null, last_sent_at: null, can_resend: false, url: null });

async function isolate(page: Page) {
  const errors: string[] = [], writes: string[] = [], scopeReads: string[] = [], laneReads: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error" && /controlled|uncontrolled/.test(message.text())) errors.push(message.text()); });
  const user = { id: "admin", agency_id: "agency", role: "agency_admin", full_name: "Fixture Staff", email: "fixture@example.test", is_active: true, capabilities: [] };
  const broadcast: WhatsAppBroadcastGroupDetail = { id: broadcastId, name: "Document October", is_archived: false, archived_at: null, created_at: timestamp, updated_at: timestamp, recipient_count: 3, total_contact_count: 3, recipient_opt_in_confirmed: true, support_contacts: [], rejected_contact_count: 0, linked_client_groups: [{ id: groupId, name: "October Trip", status: "active" }], recipients: names.slice(0, 3).map((name, i) => ({ id: `recipient-${i}`, name, phone_number: `+91987654320${i}`, normalized_phone_number: `+91987654320${i}`, welcome_delivered: true, welcome_status: "delivered", imported_fields: {}, message_statuses: [] })) };
  const review: DocumentBatchReview = { batch_id: "batch", group_id: groupId, document_type: "visa", status: "saved", uploaded_count: 3, rejected_count: 0, matched_count: 3, physical_file_count: 2, assigned_file_count: 2, assigned_passenger_count: 3, needs_assignment_count: 0, processing_upload_ids: [], saved_at: timestamp, created_at: timestamp, unmatched_documents: [], assignment_issues: [], rejected_documents: [], review_rows: names.map((name, i) => { const doc = i ? document(`document-${i}`, i === 2 ? "sent" : "not_sent") : null; return { passenger_id: `passenger-${i}`, passenger_name: name, passport_number: `P000000${i}`, departure_city: "Delhi", document: doc, documents: doc ? [doc] : [], assigned_pdf_count: doc ? 1 : 0, shared_pdf_count: i === 1 || i === 2 ? 1 : 0 }; }) };
  await page.context().addCookies([{ name: "access_token", value: "isolated-test", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  await page.route("**/api/v1/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/v1/auth/refresh") return reply({ status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (path === "/api/v1/auth/me") return reply(user);
    if (path === "/api/v1/notifications/feed") return reply({ items: [], unread_count: 0, next_cursor: null });
    if (path.startsWith("/api/v1/telemetry")) return reply({});
    if (path === "/api/v1/whatsapp/groups") return reply(url.searchParams.get("archived") === "true" ? [] : [broadcast]);
    if (path === `/api/v1/whatsapp/groups/${broadcastId}`) return reply(broadcast);
    if (path.endsWith("/recipient-roster")) return reply({ items: broadcast.recipients.map((recipient, display_order) => ({ kind: "recipient", recipient, display_order })), counts: { all: 3, sent: 0, failed: 0, rejected: 0, replaced: 0, unidentified: 0 } });
    if (path.endsWith("/source-contacts")) return reply({ sources: [], contacts: [], total_contacts: 0 });
    if (path === "/api/v1/document-distribution/groups") return reply([]);
    const lane = path.split("/")[6];
    if (path.endsWith("/update-preview")) {
      scopeReads.push(url.searchParams.get("broadcast_group_id") ?? "MISSING_SCOPE");
      return reply({ group_id: groupId, document_type: lane, preview_token: "a".repeat(64), template_name: "pending_v1", template_language: "en", can_send: true, configuration_error: null, recipients: names.slice(0, 3).map((name, i) => ({ passenger_id: `passenger-${i}`, passenger_name: name, phone_number: `+91987654320${i}`, recipient_id: `recipient-${i}`, broadcast_group_id: broadcastId, document_count: review.review_rows[i].documents.length, confirmed_count: i === 2 ? 1 : 0, eligible: i !== 2, reason: i === 2 ? "Already sent" : null, latest_update_status: null })) });
    }
    if (path.endsWith("/whatsapp-preview")) {
      scopeReads.push(url.searchParams.get("broadcast_group_id") ?? "MISSING_SCOPE");
      return reply({ group_id: groupId, batch_id: "batch", preview_token: "b".repeat(64), document_type: lane, template_name: "documents_v1", template_configured: true, linked_broadcast_count: 1, can_send: true, configuration_error: null, message_content_1: "Attached document", message_content_2: "Please review.", summary: { total_passengers: 3, total_group_passengers: 3, excluded_without_document: 0, ready: 2, retryable: 0, already_sent: 1, in_progress: 0, blocked: 0 }, recipients: names.slice(0, 3).map((name, i) => ({ passenger_id: `passenger-${i}`, passenger_name: name, passport_number: `P000000${i}`, document_id: review.review_rows[i].document?.id, document_filename: review.review_rows[i].document?.original_filename, document_type: lane, recipient_id: `recipient-${i}`, broadcast_group_id: broadcastId, phone_number: `+91987654320${i}`, delivery_status: i === 2 ? "already_sent" : "ready", eligible: i !== 2, resend_allowed: i === 2, reason: "", error_message: null })) });
    }
    if (path.endsWith("/manual-upload") && request.method() === "POST") {
      writes.push(path);
      const i = Number(path.match(/passenger-(\d)/)?.[1]);
      const doc = { ...document(`uploaded-${i}`), original_filename: "manual.pdf" };
      review.review_rows[i] = { ...review.review_rows[i], document: doc, documents: [doc], assigned_pdf_count: 1, shared_pdf_count: 0 };
      return reply(review);
    }
    if (path.startsWith(`/api/v1/document-distribution/groups/${groupId}/`) && request.method() === "GET") {
      laneReads.push(lane);
      return reply({ ...review, document_type: lane });
    }
    if (request.method() !== "GET") { writes.push(`UNEXPECTED ${request.method()} ${path}`); return reply({ detail: "No messaging is allowed in this fixture" }, 400); }
    return reply([]);
  });
  return { errors, writes, scopeReads, laneReads };
}

for (const width of [1440, 390]) {
  test(`recipient documents are scoped and manageable at ${width}px`, async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width, height: 960 });
    const state = await isolate(page);
    await page.goto("/whatsapp");
    await page.getByRole("button", { name: "Open actions for Document October" }).filter({ visible: true }).click();
    await page.getByRole("button", { name: "Recipient List", exact: true }).click();
    const recipients = page.getByRole("dialog", { name: "Recipients — Document October", exact: true });
    await recipients.getByRole("button", { name: "Documents", exact: true }).click();
    await expect(recipients.getByText("Waiting Traveller", { exact: true })).toBeVisible();
    await expect(recipients.getByText("Other broadcast passenger", { exact: true })).toHaveCount(0);
    await expect(recipients.getByLabel("Document client group")).toHaveValue(groupId);
    const lane = recipients.getByRole("combobox", { name: "Document type", exact: true });
    await expect(lane.locator("option")).toHaveCount(5);
    for (const value of ["flight_ticket", "flight_ticket_arrival", "flight_ticket_domestic", "flight_ticket_domestic_arrival", "visa"]) {
      await lane.selectOption(value);
      await expect(recipients.getByText("Waiting Traveller", { exact: true })).toBeVisible();
    }
    await recipients.getByRole("button", { name: "Shared PDF (2)", exact: true }).click();
    await expect(recipients.getByText("Waiting Traveller", { exact: true })).toHaveCount(0);
    await recipients.getByRole("button", { name: "All (3)", exact: true }).click();
    await recipients.getByRole("button", { name: "Waiting Traveller document actions" }).click();
    await expect(recipients.getByRole("menuitem", { name: "Upload document", exact: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(recipients).toBeVisible();
    await expect(recipients.getByRole("button", { name: "Waiting Traveller document actions" })).toBeFocused();
    await recipients.getByRole("button", { name: "Waiting Traveller document actions" }).click();
    await page.getByRole("menuitem", { name: "Upload document", exact: true }).click();
    const upload = page.getByRole("dialog", { name: "Upload document", exact: true });
    await upload.getByLabel("Choose PDF").setInputFiles({ name: "manual.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\nfixture") });
    await upload.getByRole("button", { name: "Upload and save", exact: true }).click();
    await expect(upload).toHaveCount(0);
    await recipients.getByRole("button", { name: "Shared Traveller document actions" }).click();
    await page.getByRole("menuitem", { name: "Replace document", exact: true }).click();
    const replace = page.getByRole("dialog", { name: "Replace document", exact: true });
    await expect(replace.getByLabel("Document to replace")).toHaveValue("document-1");
    await replace.getByRole("button", { name: "Cancel", exact: true }).click();
    await recipients.getByRole("checkbox", { name: "Select all assignments for Shared Traveller" }).check();
    await recipients.getByRole("button", { name: "Send WhatsApp Broadcast", exact: true }).click();
    const chooser = page.getByRole("dialog", { name: "Send WhatsApp broadcast", exact: true });
    await chooser.getByRole("button", { name: "Send documents", exact: true }).click();
    const send = page.getByRole("dialog", { name: "Preview WhatsApp document delivery", exact: true });
    await expect(send.getByRole("button", { name: "Send individually to 1", exact: true })).toBeEnabled();
    await send.getByRole("button", { name: "Close delivery preview" }).click();
    await recipients.getByRole("button", { name: "Send WhatsApp Broadcast", exact: true }).click();
    await chooser.getByRole("button", { name: "Inform / update", exact: true }).click();
    const update = page.getByRole("dialog", { name: "Inform / update — Visa", exact: true });
    await expect(update.getByRole("checkbox", { name: "Select Waiting Traveller" })).toBeChecked();
    await expect(update.getByRole("checkbox", { name: "Select Confirmed Traveller" })).toBeDisabled();
    await expect(update.getByText("Other broadcast passenger", { exact: true })).toHaveCount(0);
    await update.getByRole("button", { name: "Cancel", exact: true }).click();
    const screenshot = testInfo.outputPath(`recipient-documents-${width}.png`);
    await page.screenshot({ path: screenshot, fullPage: true });
    await testInfo.attach("Scoped recipient document management", { path: screenshot, contentType: "image/png" });
    expect(state.scopeReads.length).toBeGreaterThan(5);
    expect(new Set(state.scopeReads)).toEqual(new Set([broadcastId]));
    expect(new Set(state.laneReads)).toEqual(new Set(["visa", "flight_ticket", "flight_ticket_arrival", "flight_ticket_domestic", "flight_ticket_domestic_arrival"]));
    expect(state.writes).toEqual([`/api/v1/document-distribution/groups/${groupId}/visa/passengers/passenger-0/manual-upload`]);
    expect(state.errors).toEqual([]);
  });
}
