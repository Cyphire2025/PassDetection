import { expect, test, type Page } from "@playwright/test";
import type { DocumentBatchReview, DistributedDocument } from "../types/document-distribution.types";
import type { WhatsAppBroadcastGroupDetail } from "../features/whatsapp/api/whatsapp.api";

const groupId = "document-client-group";
const broadcastId = "document-broadcast";
const timestamp = "2026-10-16T00:00:00Z";
const names = ["Waiting Traveller", "Shared Traveller", "Confirmed Traveller", "Other broadcast passenger"];
const lanes = ["flight_ticket", "flight_ticket_arrival", "flight_ticket_domestic", "flight_ticket_domestic_arrival", "visa"];

function document(id: string, status = "not_sent"): DistributedDocument {
  return {
    id, updated_at: timestamp, original_filename: "shared.pdf", document_type: "visa",
    detected_type: "visa", match_status: "matched", match_confidence: .97,
    match_reason: null, extracted_name: null, extracted_passport_number: null,
    extracted_reference: null, source: "manual", delivery_status: status,
    sent_to: null, last_sent_at: null, can_resend: false,
    url: `http://127.0.0.1:3199/synthetic/${id === "document-1" || id === "document-2" ? "shared" : id}.pdf?signature=synthetic`,
  };
}

async function isolate(page: Page) {
  const errors: string[] = [], writes: string[] = [], scopeReads: string[] = [], laneReads: string[] = [];
  const updateAudiences: unknown[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => {
    if (message.type() === "error" && /controlled|uncontrolled/.test(message.text())) errors.push(message.text());
  });
  const user = { id: "admin", agency_id: "agency", role: "agency_admin", full_name: "Fixture Staff", email: "fixture@example.test", is_active: true, capabilities: [] };
  const broadcast: WhatsAppBroadcastGroupDetail = {
    id: broadcastId, name: "Document October", is_archived: false, archived_at: null,
    created_at: timestamp, updated_at: timestamp, recipient_count: 3, total_contact_count: 3,
    recipient_opt_in_confirmed: true, support_contacts: [], rejected_contact_count: 0,
    linked_client_groups: [{ id: groupId, name: "October Trip", status: "active" }],
    recipients: names.slice(0, 3).map((name, i) => ({
      id: `recipient-${i}`, name, phone_number: `+91987654320${i}`,
      normalized_phone_number: `+91987654320${i}`, welcome_delivered: true,
      welcome_status: "delivered", imported_fields: {}, message_statuses: [],
    })),
  };
  const review: DocumentBatchReview = {
    batch_id: "batch", group_id: groupId, document_type: "visa", status: "saved",
    uploaded_count: 3, rejected_count: 0, matched_count: 3, physical_file_count: 2,
    assigned_file_count: 2, assigned_passenger_count: 3, needs_assignment_count: 0,
    processing_upload_ids: [], saved_at: timestamp, created_at: timestamp,
    unmatched_documents: [], assignment_issues: [], rejected_documents: [],
    review_rows: names.map((name, i) => {
      const doc = i ? document(`document-${i}`, i === 2 ? "sent" : "not_sent") : null;
      return {
        passenger_id: `passenger-${i}`, passenger_name: name, passport_number: `P000000${i}`,
        departure_city: "Delhi", document: doc, documents: doc ? [doc] : [],
        assigned_pdf_count: doc ? 1 : 0, shared_pdf_count: i === 1 || i === 2 ? 1 : 0,
      };
    }),
  };
  await page.context().addCookies([{
    name: "access_token", value: "isolated-test", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax",
  }]);
  await page.route("**/api/v1/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/v1/auth/refresh") return reply({ status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (path === "/api/v1/auth/me") return reply(user);
    if (path === "/api/v1/notifications/feed") return reply({ items: [], unread_count: 0, next_cursor: null });
    if (path.startsWith("/api/v1/telemetry")) return reply({});
    if (path === "/api/v1/whatsapp/message-catalog") return reply([{
      id: "update", message_type: "update", label: "Trip update", description: "Send an update using submission and document delivery filters.",
      category: "Trip updates", image_required: false, audience: "update", repeatable: true,
      fields: [{ key: "message_content", label: "Update message", kind: "textarea", required: true, max_length: 600 }],
    }]);
    if (path === "/api/v1/whatsapp/groups") return reply(url.searchParams.get("archived") === "true" ? [] : [broadcast]);
    if (path === `/api/v1/whatsapp/groups/${broadcastId}`) return reply(broadcast);
    if (path.endsWith("/recipient-roster")) return reply({ items: broadcast.recipients.map((recipient, display_order) => ({ kind: "recipient", recipient, display_order })), counts: { all: 3, sent: 0, failed: 0, rejected: 0, replaced: 0, unidentified: 0 } });
    if (path === `/api/v1/whatsapp/groups/${broadcastId}/passenger-links`) {
      return reply(names.slice(0, 3).map((_, i) => ({ group_id: groupId, passenger_id: `passenger-${i}` })));
    }
    if (path.endsWith("/source-contacts")) return reply({ sources: [], contacts: [], total_contacts: 0 });
    if (path === "/api/v1/document-distribution/groups") return reply([{
      group_id: groupId, group_name: "October Trip", group_status: "active", destination: "Dubai",
      travel_date: "2026-10-22", total_passengers: 4, visa_assigned_count: 3,
      flight_ticket_assigned_count: 3, flight_ticket_arrival_assigned_count: 3,
      flight_ticket_domestic_assigned_count: 3, flight_ticket_domestic_arrival_assigned_count: 3, other_assigned_count: 0,
    }]);
    const lane = path.split("/")[6];
    if (path === `/api/v1/document-distribution/groups/${groupId}/updates/preview`) {
      const audience = request.postDataJSON();
      updateAudiences.push(audience);
      return reply({
        group_id: groupId, audience, preview_token: "a".repeat(64), template_name: "pending_v1",
        template_language: "en", can_send: true, configuration_error: null,
        recipients: names.map((name, i) => ({
          audience_key: `recipient:recipient-${i}`, name, passenger_id: `passenger-${i}`,
          phone_number: `+91987654320${i}`, phone_source: "submitted", submission_status: "submitted",
          recipient_id: `recipient-${i}`, broadcast_group_id: i === 3 ? "other-broadcast" : broadcastId,
          document_count: review.review_rows[i].documents.length, confirmed_count: i === 2 ? 1 : 0,
          eligible: i !== 2, reason: i === 2 ? "Already sent" : null,
          latest_update_status: null, latest_update_at: null,
        })),
      });
    }
    if (path.endsWith("/whatsapp-preview")) {
      scopeReads.push(url.searchParams.get("broadcast_group_id") ?? "MISSING_SCOPE");
      return reply({
        group_id: groupId, batch_id: "batch", preview_token: "b".repeat(64), document_type: lane,
        template_name: "documents_v1", template_configured: true, linked_broadcast_count: 1,
        can_send: true, configuration_error: null, message_content_1: "Attached document", message_content_2: "Please review.",
        summary: { total_passengers: 3, total_group_passengers: 4, excluded_without_document: 0, ready: 2, retryable: 0, already_sent: 1, in_progress: 0, blocked: 0 },
        recipients: names.map((name, i) => ({
          passenger_id: `passenger-${i}`, passenger_name: name, passport_number: `P000000${i}`,
          document_id: review.review_rows[i].document?.id, document_filename: review.review_rows[i].document?.original_filename,
          document_type: lane, recipient_id: `recipient-${i}`, broadcast_group_id: i === 3 ? "other-broadcast" : broadcastId,
          phone_number: `+91987654320${i}`, delivery_status: i === 2 ? "already_sent" : "ready",
          eligible: i !== 2, resend_allowed: i === 2, reason: "", error_message: null,
        })),
      });
    }
    if (path.endsWith("/manual-upload") && request.method() === "POST") {
      writes.push(path);
      const i = Number(path.match(/passenger-(\d)/)?.[1]);
      const doc = { ...document(`uploaded-${i}`), original_filename: "manual.pdf" };
      review.review_rows[i] = { ...review.review_rows[i], document: doc, documents: [doc], assigned_pdf_count: 1, shared_pdf_count: 0 };
      review.physical_file_count = 3;
      review.assigned_file_count = 3;
      review.assigned_passenger_count = 4;
      return reply(review);
    }
    if (path.startsWith(`/api/v1/document-distribution/groups/${groupId}/`) && request.method() === "GET") {
      laneReads.push(lane);
      return reply({
        ...review, document_type: lane,
        review_rows: review.review_rows.map(row => ({
          ...row,
          document: row.document ? { ...row.document, document_type: lane, detected_type: lane } : null,
          documents: row.documents.map(doc => ({ ...doc, document_type: lane, detected_type: lane })),
        })),
      });
    }
    if (request.method() !== "GET") {
      writes.push(`UNEXPECTED ${request.method()} ${path}`);
      return reply({ detail: "No messaging is allowed in this fixture" }, 400);
    }
    return reply([]);
  });
  return { errors, writes, scopeReads, laneReads, updateAudiences };
}

for (const width of [1440, 390]) {
  test(`recipient documents are scoped and manageable at ${width}px`, async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width, height: 960 });
    const state = await isolate(page);
    await page.goto("/whatsapp");
    await page.getByRole("link", { name: "Open Document October", exact: true }).click();
    const sections = page.getByRole("navigation", { name: "Broadcast sections" });
    await sections.getByRole("link", { name: "Documents", exact: true }).click();
    await expect(page.getByText("Waiting Traveller", { exact: true })).toBeVisible();
    await expect(page.getByText("Other broadcast passenger", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Manage document assignments", exact: true })).toHaveAttribute("href", `/documents/distribution/${groupId}`);
    const lane = page.getByRole("combobox", { name: "Document type", exact: true });
    await expect(lane.locator("option")).toHaveCount(5);
    for (const value of lanes) {
      await lane.selectOption(value);
      await expect(page.getByText("Waiting Traveller", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Send documents", exact: true }).click();
      await expect(page.getByRole("checkbox", { name: "Select document for Shared Traveller", exact: true })).toBeChecked();
      await expect(page.getByRole("checkbox", { name: "Select document for Other broadcast passenger", exact: true })).toHaveCount(0);
      await page.getByRole("button", { name: "Passenger documents", exact: true }).click();
    }
    await page.getByRole("button", { name: "Shared PDF (2)", exact: true }).click();
    await expect(page.getByText("Waiting Traveller", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "All (3)", exact: true }).click();
    await page.getByRole("link", { name: "Manage document assignments", exact: true }).click();
    await page.getByRole("link", { name: "Open Visa", exact: true }).click();
    // This is the source group's management workspace; broadcast-only filtering belongs above.
    await expect(page.getByText("Other broadcast passenger", { exact: true })).toBeVisible();
    const actions = page.getByRole("button", { name: "Waiting Traveller document actions", exact: true });
    await actions.click();
    await expect(page.getByRole("menuitem", { name: "Upload document", exact: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(actions).toBeFocused();
    await actions.click();
    await page.getByRole("menuitem", { name: "Upload document", exact: true }).click();
    const upload = page.getByRole("dialog", { name: "Upload document", exact: true });
    await upload.getByLabel("Choose PDF").setInputFiles({ name: "manual.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\nfixture") });
    await upload.getByRole("button", { name: "Upload and save", exact: true }).click();
    await expect(upload).toHaveCount(0);
    await page.getByRole("button", { name: "Shared Traveller document actions", exact: true }).click();
    await page.getByRole("menuitem", { name: "Replace document", exact: true }).click();
    const replace = page.getByRole("dialog", { name: "Replace document", exact: true });
    await expect(replace.getByLabel("Document to replace")).toHaveValue("document-1");
    await replace.getByRole("button", { name: "Cancel", exact: true }).click();
    await page.goto(`/whatsapp/${broadcastId}/documents`);
    await expect(page.getByText("Other broadcast passenger", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Send documents", exact: true }).click();
    await page.getByRole("checkbox", { name: "Select document for Waiting Traveller", exact: true }).uncheck();
    await expect(page.getByRole("checkbox", { name: "Select document for Confirmed Traveller", exact: true })).not.toBeChecked();
    await expect(page.getByRole("checkbox", { name: "Select document for Other broadcast passenger", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Review message", exact: true }).click();
    const delivery = page.getByRole("dialog", { name: "Review document delivery", exact: true });
    await expect(delivery.getByRole("button", { name: "Send 1 messages", exact: true })).toBeEnabled();
    await expect(delivery).toContainText("0 explicit resends");
    await delivery.getByRole("button", { name: "Back to editing", exact: true }).click();
    await sections.getByRole("link", { name: "Send messages", exact: true }).click();
    await page.getByRole("button", { name: /^Trip update Send an update/ }).click();
    await page.getByRole("textbox", { name: "Update message", exact: true }).fill("Your visa processing status is available.");
    await page.getByRole("combobox", { name: "Document delivery", exact: true }).selectOption("pending");
    await expect(page.getByRole("checkbox", { name: "Select Waiting Traveller", exact: true })).toBeChecked();
    await expect(page.getByRole("checkbox", { name: "Select Confirmed Traveller", exact: true })).toBeDisabled();
    await expect(page.getByText("Other broadcast passenger", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Review message", exact: true }).click();
    const update = page.getByRole("dialog", { name: "Review trip update", exact: true });
    await expect(update.getByRole("button", { name: "Send 2 messages", exact: true })).toBeEnabled();
    await update.getByRole("button", { name: "Back to editor", exact: true }).click();
    const screenshot = testInfo.outputPath(`recipient-documents-${width}.png`);
    await page.screenshot({ path: screenshot, fullPage: true });
    await testInfo.attach("Scoped recipient document management", { path: screenshot, contentType: "image/png" });
    expect(state.scopeReads.length).toBeGreaterThan(5);
    expect(new Set(state.scopeReads)).toEqual(new Set([broadcastId]));
    expect(new Set(state.laneReads)).toEqual(new Set(lanes));
    expect(state.updateAudiences).toContainEqual({ submission_status: "all", document_status: "pending", document_type: "visa" });
    expect(state.writes).toEqual([`/api/v1/document-distribution/groups/${groupId}/visa/passengers/passenger-0/manual-upload`]);
    expect(state.errors).toEqual([]);
  });
}
