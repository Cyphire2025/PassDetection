import { expect, test, type Page } from "@playwright/test";
import type { DocumentBatchReview, DistributedDocument } from "../types/document-distribution.types";

const groupId = "management-group";
const updated = "2026-10-15T10:00:00Z";
const names = ["Missing Traveller", "Shared One", "Shared Two"];
const user = { id: "admin", agency_id: "agency", role: "agency_admin", full_name: "Test Staff", email: "staff@example.test", is_active: true, capabilities: [], created_at: updated, updated_at: updated, last_login_at: null };
const doc = (id: string, status = "not_sent"): DistributedDocument => ({ id, updated_at: updated, original_filename: "group-ticket.pdf", document_type: "visa", detected_type: "visa", match_status: "matched", match_confidence: 97, match_reason: null, extracted_name: null, extracted_passport_number: null, extracted_reference: null, source: "manual", delivery_status: status, sent_to: null, last_sent_at: null, can_resend: false, url: null });

async function fixture(page: Page) {
  const writes: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const review: DocumentBatchReview = {
    batch_id: "batch", group_id: groupId, document_type: "visa", status: "saved", uploaded_count: 1,
    rejected_count: 0, matched_count: 2, physical_file_count: 1, assigned_file_count: 1, assigned_passenger_count: 2,
    needs_assignment_count: 0, processing_upload_ids: [], saved_at: updated, created_at: updated,
    unmatched_documents: [], assignment_issues: [], rejected_documents: [],
    review_rows: names.map((name, index) => { const document = index ? doc(`document-${index}`, index === 2 ? "sent" : "not_sent") : null; return { passenger_id: `passenger-${index}`, passenger_name: name, passport_number: `P000000${index}`, departure_city: "Delhi", document, documents: document ? [document] : [], assigned_pdf_count: document ? 1 : 0, shared_pdf_count: document ? 1 : 0 }; }),
  };
  await page.context().addCookies([{ name: "access_token", value: "isolated-document-fixture", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  await page.route("**/api/v1/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/v1/auth/refresh") return reply({ status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (path === "/api/v1/auth/me") return reply(user);
    if (path === "/api/v1/notifications/feed") return reply({ items: [], unread_count: 0, next_cursor: null });
    if (path.startsWith("/api/v1/telemetry")) return reply({});
    if (path === "/api/v1/document-distribution/groups") return reply([{ group_id: groupId, group_name: "Test October Trip", group_status: "active", destination: "Dubai", travel_date: "2026-10-22", total_passengers: 3, visa_assigned_count: 2, flight_ticket_assigned_count: 0, flight_ticket_arrival_assigned_count: 0, flight_ticket_domestic_assigned_count: 0, flight_ticket_domestic_arrival_assigned_count: 0, other_assigned_count: 0 }]);
    if (path === `/api/v1/document-distribution/groups/${groupId}/visa`) return reply(review);
    if (path.endsWith("/update-preview")) return reply({ group_id: groupId, document_type: "visa", preview_token: "a".repeat(64), template_name: "pending_v1", template_language: "en", can_send: true, configuration_error: null, recipients: names.map((name, index) => ({ passenger_id: `passenger-${index}`, passenger_name: name, phone_number: `+91987654320${index}`, recipient_id: `recipient-${index}`, broadcast_group_id: "broadcast", document_count: review.review_rows[index].documents.length, confirmed_count: index === 2 ? 1 : 0, eligible: index !== 2, reason: index === 2 ? "All assigned documents have a confirmed send." : null, latest_update_status: null })) });
    if (path.endsWith("/manual-upload") && request.method() === "POST") {
      writes.push(path);
      const index = Number(path.match(/passenger-(\d)/)?.[1]);
      const replacement = { ...doc(`uploaded-${index}`), original_filename: "manual.pdf" };
      review.review_rows[index] = { ...review.review_rows[index], document: replacement, documents: [replacement], assigned_pdf_count: 1, shared_pdf_count: 0 };
      review.assigned_passenger_count = 3;
      return reply(review);
    }
    if (request.method() !== "GET") { writes.push(`UNEXPECTED ${request.method()} ${path}`); return reply({ detail: "No real sends in this test" }, 400); }
    return reply([]);
  });
  return { writes, errors };
}

for (const width of [1440, 390]) {
  test(`document management upload, replace, shared filter and update preview at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 960 });
    const state = await fixture(page);
    await page.goto(`/documents/distribution/visa/${groupId}`);
    await expect(page.getByText("Missing Traveller", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Shared PDF (2)", exact: true }).click();
    await expect(page.getByText("Missing Traveller", { exact: true })).toBeHidden();
    await expect(page.getByText("Shared One", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "All (3)", exact: true }).click();
    await page.getByRole("button", { name: "Missing Traveller document actions" }).click();
    await page.getByRole("menuitem", { name: "Upload document", exact: true }).click();
    const upload = page.getByRole("dialog", { name: "Upload document", exact: true });
    await upload.getByLabel("Choose PDF").setInputFiles({ name: "manual.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\nfixture") });
    await upload.getByRole("button", { name: "Upload and save" }).click();
    await expect(upload).toBeHidden();
    await page.getByRole("button", { name: "Shared One document actions" }).click();
    await page.getByRole("menuitem", { name: "Replace document", exact: true }).click();
    const replace = page.getByRole("dialog", { name: "Replace document", exact: true });
    await expect(replace.getByLabel("Document to replace")).toHaveValue("document-1");
    await replace.getByRole("button", { name: "Cancel", exact: true }).click();
    await page.getByRole("button", { name: "Send WhatsApp Broadcast", exact: true }).click();
    const chooser = page.getByRole("dialog", { name: "Send WhatsApp broadcast", exact: true });
    await expect(chooser.getByRole("button", { name: "Send documents", exact: true })).toBeVisible();
    await chooser.getByRole("button", { name: "Inform / update", exact: true }).click();
    const update = page.getByRole("dialog", { name: "Inform / update — Visa", exact: true });
    await expect(update.getByRole("checkbox", { name: "Select Missing Traveller" })).toBeChecked();
    await expect(update.getByRole("checkbox", { name: "Select Shared Two" })).toBeDisabled();
    await update.getByLabel("Your update message").fill("Your visa is being processed. We will share it once approved.");
    await expect(update.getByRole("button", { name: "Send update to 2" })).toBeInViewport();
    await page.screenshot({ path: `test-results/document-update-preview-${width}.png`, fullPage: true });
    await update.getByRole("button", { name: "Cancel", exact: true }).click();
    expect(state.writes).toEqual([`/api/v1/document-distribution/groups/${groupId}/visa/passengers/passenger-0/manual-upload`]);
    expect(state.errors).toEqual([]);
  });
}
