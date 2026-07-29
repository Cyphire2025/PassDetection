export type DistributionDocumentType = "visa" | "flight_ticket" | "other";

export interface DocumentDistributionGroup {
  group_id: string;
  group_name: string;
  group_status: string;
  destination: string | null;
  travel_date: string | null;
  total_passengers: number;
}

export interface RejectedDistributedDocument {
  filename: string;
  detected_type: string;
  reason: string;
}

export interface VerifiedDistributedDocument {
  filename: string;
  detected_type: string;
  accepted: boolean;
  reason: string;
  matched_passenger_id: string | null;
  matched_passenger_name: string | null;
  matched_passenger_ids: string[];
  matched_passenger_names: string[];
  match_confidence: number;
  match_status: string | null;
  match_reason: string | null;
}

export interface DocumentVerificationResult {
  group_id: string;
  document_type: DistributionDocumentType | string;
  total_count: number;
  accepted_count: number;
  rejected_count: number;
  files: VerifiedDistributedDocument[];
}

export interface DistributedDocument {
  id: string;
  original_filename: string;
  document_type: DistributionDocumentType | string;
  detected_type: string;
  match_status: "matched" | "needs_review" | "duplicate_document" | string;
  match_confidence: number;
  match_reason: string | null;
  extracted_name: string | null;
  extracted_passport_number: string | null;
  extracted_reference: string | null;
  url: string | null;
}

export interface DocumentPassengerReviewRow {
  passenger_id: string;
  passenger_name: string;
  passport_number: string | null;
  departure_city: string | null;
  document: DistributedDocument | null;
}

export interface DocumentBatchReview {
  batch_id: string | null;
  group_id: string;
  document_type: DistributionDocumentType | string;
  status: string;
  uploaded_count: number;
  rejected_count: number;
  matched_count: number;
  saved_at: string | null;
  created_at: string | null;
  review_rows: DocumentPassengerReviewRow[];
  unmatched_documents: DistributedDocument[];
  rejected_documents: RejectedDistributedDocument[];
}

export type DocumentDeliveryPreviewStatus =
  | "ready"
  | "retryable"
  | "already_sent"
  | "queued"
  | "processing"
  | "delivery_unknown"
  | "blocked";

export interface DocumentDeliveryPreviewRecipient {
  passenger_id: string;
  passenger_name: string;
  passport_number: string | null;
  document_id: string | null;
  document_filename: string | null;
  document_type: DistributionDocumentType | string;
  recipient_id: string | null;
  broadcast_group_id: string | null;
  broadcast_name: string | null;
  phone_number: string | null;
  delivery_id: string | null;
  delivery_status: DocumentDeliveryPreviewStatus | string;
  eligible: boolean;
  reason: string;
  error_message: string | null;
  message_preview: string | null;
}

export interface DocumentDeliveryPreview {
  group_id: string;
  batch_id: string;
  document_type: DistributionDocumentType | string;
  template_name: string | null;
  template_configured: boolean;
  linked_broadcast_count: number;
  can_send: boolean;
  configuration_error: string | null;
  message_content_1: string;
  message_content_2: string;
  summary: {
    total_passengers: number;
    ready: number;
    retryable: number;
    already_sent: number;
    in_progress: number;
    blocked: number;
  };
  recipients: DocumentDeliveryPreviewRecipient[];
}

export interface SendDocumentBroadcastResult {
  send_batch_id: string | null;
  queued_count: number;
  skipped_count: number;
  message: string;
}

export interface DocumentDeliveryTrackingRow {
  delivery_id: string;
  passenger_id: string | null;
  passenger_name: string;
  passport_number: string | null;
  document_type: DistributionDocumentType | string;
  document_filename: string;
  phone_number: string;
  status: string;
  error_message: string | null;
  status_updated_at: string;
}

export interface DocumentDeliveryTracking {
  group_id: string;
  counts: {
    total: number;
    queued: number;
    sent: number;
    delivered: number;
    read: number;
    failed: number;
    delivery_unknown: number;
  };
  deliveries: DocumentDeliveryTrackingRow[];
}
