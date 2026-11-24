import type { DocumentDeliveryPreview } from "@/types/document-distribution.types";

export function documentPreview(overrides: Partial<DocumentDeliveryPreview> = {}): DocumentDeliveryPreview {
  return {
    group_id: "trip", batch_id: "batch", preview_token: "a".repeat(64), document_type: "visa", template_name: "documents_v1", template_configured: true, linked_broadcast_count: 1, can_send: true, configuration_error: null, message_content_1: "Your visa is attached.", message_content_2: "Have a good journey.", summary: { total_passengers: 1, total_group_passengers: 1, total_documents: 1, excluded_without_document: 0, ready: 1, retryable: 0, already_sent: 0, in_progress: 0, blocked: 0, welcome_required: 0 }, recipients: [{ passenger_id: "mother", passenger_name: "Mother", passport_number: "SAMPLE", document_id: "visa-1", document_filename: "mother-visa.pdf", document_type: "visa", recipient_id: null, broadcast_group_id: "source", broadcast_name: "Company qualifiers", phone_number: "+919900000001", phone_source: "submission", welcome_status: "not_required", welcome_required: false, delivery_id: null, delivery_status: "ready", eligible: true, resend_allowed: false, reason: "Ready to send.", error_message: null, message_preview: null }], ...overrides,
  };
}
