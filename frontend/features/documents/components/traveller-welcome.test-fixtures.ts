import type { DocumentDeliveryPreview, TravellerWelcomePreview, TravellerWelcomeRecipient } from "@/types/document-distribution.types";

export function welcomeRecipient(overrides: Partial<TravellerWelcomeRecipient> = {}): TravellerWelcomeRecipient {
  return { phone_number: "+919900000001", passenger_ids: ["mother", "father"], passenger_names: ["Mother", "Father"], status: "required", eligible: true, reason: "Welcome must be delivered before documents.", rendered_message: "Hello Mother and Father, welcome to the company trip.", ...overrides };
}

export function welcomePreview(overrides: Partial<TravellerWelcomePreview> = {}): TravellerWelcomePreview {
  return {
    group_id: "trip", preview_token: "review-token", source_broadcast_id: "source", source_broadcast_name: "Company qualifiers", sources: [{ id: "source", name: "Company qualifiers" }], template_name: "welcome_v1", template_configured: true, can_send: true, configuration_error: null, header_image_url: null,
    summary: { total_numbers: 3, needs_welcome: 1, already_welcomed: 1, in_progress: 1, blocked: 0 },
    recipients: [welcomeRecipient(), welcomeRecipient({ phone_number: "+919900000002", passenger_ids: ["original"], passenger_names: ["Original traveller"], status: "delivered", eligible: false, reason: "Welcome was already delivered." }), welcomeRecipient({ phone_number: "+919900000003", passenger_ids: ["pending"], passenger_names: ["Pending traveller"], status: "sent", eligible: false, reason: "Waiting for welcome delivery." })], poll_after_seconds: 5, ...overrides,
  };
}

export function documentPreview(overrides: Partial<DocumentDeliveryPreview> = {}): DocumentDeliveryPreview {
  return {
    group_id: "trip", batch_id: "batch", document_type: "visa", template_name: "documents_v1", template_configured: true, linked_broadcast_count: 1, can_send: true, configuration_error: null, message_content_1: "Your visa is attached.", message_content_2: "Have a good journey.", summary: { total_passengers: 1, ready: 0, retryable: 0, already_sent: 0, in_progress: 0, blocked: 1, welcome_required: 1 }, recipients: [{ passenger_id: "mother", passenger_name: "Mother", passport_number: "SAMPLE", document_id: "visa-1", document_filename: "mother-visa.pdf", document_type: "visa", recipient_id: null, broadcast_group_id: "source", broadcast_name: "Company qualifiers", phone_number: "+919900000001", phone_source: "submission", welcome_status: "required", welcome_required: true, delivery_id: null, delivery_status: "blocked", eligible: false, resend_allowed: false, reason: "Welcome delivery is required.", error_message: null, message_preview: null }], ...overrides,
  };
}
