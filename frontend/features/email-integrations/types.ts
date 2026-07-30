export interface EmailProviderAvailability {
  provider: "gmail" | "outlook";
  label: string;
  configured: boolean;
}

export interface EmailIntegrationStatus {
  enabled: boolean;
  sync_enabled: boolean;
  attachment_processing_enabled: boolean;
  auto_actions_enabled: boolean;
  providers: EmailProviderAvailability[];
}

export interface EmailConnection {
  id: string;
  agency_id: string;
  agency_name: string;
  provider: "gmail" | "outlook";
  email_address: string;
  status: string;
  last_successful_sync_at: string | null;
  last_sync_attempt_at: string | null;
  last_error_message: string | null;
  allowed_actions: string[];
}

export interface EmailAuthorizationResponse {
  authorization_url: string;
}

export interface EmailConnectionActionResponse {
  connection_id: string;
  status: string;
  message: string;
}

export interface EmailIntegrationSummary {
  connected_accounts: number;
  relevant_emails_today: number;
  documents_retrieved_today: number;
  automatically_matched_today: number;
  revisions_detected_today: number;
  pending_review: number;
  retrieval_failures_today: number;
}

export interface EmailReviewItem {
  id: string;
  email_message_id: string;
  artifact_id: string | null;
  status: string;
  review_type: string;
  sender_email: string;
  subject: string;
  received_at: string;
  artifact_name: string | null;
  artifact_kind: string | null;
  artifact_detected_type: string | null;
  proposed_group_id: string | null;
  proposed_group_name: string | null;
  proposed_passenger_id: string | null;
  proposed_passenger_name: string | null;
  confidence: number;
  evidence: string[];
  conflicts: string[];
  proposed_action: string;
  allowed_actions: EmailReviewAction[];
  revision: number;
  created_at: string;
}

export interface EmailReviewGroupOption {
  id: string;
  name: string;
  destination: string | null;
  travel_date: string | null;
}

export interface EmailReviewPassengerOption {
  id: string;
  group_id: string;
  name: string;
  passport_number_hint: string | null;
}

export interface EmailReviewOptions {
  groups: EmailReviewGroupOption[];
  passengers: EmailReviewPassengerOption[];
}

export type EmailReviewAction =
  | "approve"
  | "assign"
  | "mark_unrelated"
  | "reject"
  | "retry"
  | "defer";

export interface ResolveEmailReviewRequest {
  action: EmailReviewAction;
  group_id?: string;
  passenger_id?: string;
  document_type?: "visa" | "flight_ticket";
  expected_revision: number;
}

export interface EmailReviewActionResponse {
  review_id: string;
  status: string;
  message: string;
}

export interface EmailActivityItem {
  message_id: string;
  connection_id: string;
  account_email: string;
  sender_email: string;
  subject: string;
  received_at: string;
  relevance_status: string;
  processing_status: string;
  group_name: string | null;
  retrieved_count: number;
  matched_count: number;
  review_count: number;
  failure_count: number;
}

export interface EmailArtifactDetail {
  id: string;
  kind: string;
  filename: string | null;
  source_host: string | null;
  verified_content_type: string | null;
  byte_size: number | null;
  retrieval_status: string;
  processing_status: string;
  detected_type: string | null;
  match_confidence: number | null;
  group_id: string | null;
  passenger_id: string | null;
  error_message: string | null;
}

export interface EmailActivityEvent {
  id: string;
  event_type: string;
  status: string;
  title: string;
  detail: string | null;
  created_at: string;
}

export interface EmailMessageDetail {
  id: string;
  connection_id: string;
  account_email: string;
  sender_email: string;
  sender_name: string | null;
  recipients: string[];
  subject: string;
  body_excerpt: string;
  received_at: string;
  relevance_status: string;
  relevance_confidence: number;
  relevance_evidence: string[];
  processing_status: string;
  group_id: string | null;
  group_name: string | null;
  ai_used: boolean;
  artifacts: EmailArtifactDetail[];
  events: EmailActivityEvent[];
}
