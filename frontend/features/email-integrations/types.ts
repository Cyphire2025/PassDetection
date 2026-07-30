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
  ai_enabled: boolean;
  ai_notifications_enabled: boolean;
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
  ai_processing_enabled: boolean;
  ai_effective_enabled: boolean;
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

export interface EmailAiConnectionSettingsResponse {
  connection_id: string;
  enabled: boolean;
  effective_enabled: boolean;
  message: string;
}

export type EmailAiRolloutScope = "agency" | "user" | "connection";

export interface EmailAiRolloutTarget {
  scope_type: EmailAiRolloutScope;
  target_id: string;
  agency_id: string;
  owner_user_id: string | null;
  connection_id: string | null;
  label: string;
  detail: string | null;
  direct_enabled: boolean | null;
  effective_enabled: boolean;
  updated_at: string | null;
}

export interface EmailAiRolloutTargetsResponse {
  global_enabled: boolean;
  global_notifications_enabled: boolean;
  scope_type: EmailAiRolloutScope;
  items: EmailAiRolloutTarget[];
  truncated: boolean;
}

export interface UpdateEmailAiRolloutPolicyRequest {
  scope_type: EmailAiRolloutScope;
  target_id: string;
  agency_id: string;
  enabled: boolean;
  expected_updated_at: string | null;
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

export type EmailOperationalInboxView =
  | "needs_attention"
  | "upcoming_deadlines"
  | "drafts_ready"
  | "waiting"
  | "completed_automatically"
  | "all_activity";

export interface EmailInboxDeadline {
  id: string;
  deadline_type: string;
  source_phrase: string;
  source_timezone: string;
  due_at: string | null;
  confidence: number;
  is_ambiguous: boolean;
  status: string;
  updated_at: string;
}

export type EmailDeadlineDecisionAction =
  | "acknowledge"
  | "complete"
  | "dismiss";

export type EmailActiveDeadlineStatus =
  | "detected"
  | "review_required"
  | "acknowledged";

export interface DecideEmailDeadlineRequest {
  action: EmailDeadlineDecisionAction;
  expected_status: EmailActiveDeadlineStatus;
  expected_updated_at: string;
}

export type EmailProposalDecisionAction =
  | "approve"
  | "reject"
  | "dismiss";

export interface EmailInboxProposal {
  id: string;
  action_type: string;
  risk_level: string;
  status: string;
  explanation: string;
  confidence: number;
  requires_approval: boolean;
  allowed_actions: EmailProposalDecisionAction[];
  revision: number;
}

export interface EmailInboxDraft {
  id: string;
  recipients: string[];
  subject: string;
  body_text: string;
  status: string;
  revision: number;
  sending_available: false;
  updated_at: string;
}

export type EmailDraftDecisionAction = "approve" | "dismiss";

export interface DecideEmailDraftRequest {
  action: EmailDraftDecisionAction;
  expected_revision: number;
}

export interface EmailOperationalInboxItem {
  message_id: string;
  analysis_id: string;
  connection_id: string;
  account_email: string;
  provider: string;
  sender_email: string;
  sender_name: string | null;
  subject: string;
  received_at: string;
  summary: string;
  intent: string;
  priority: string;
  confidence: number;
  needs_attention: boolean;
  group_id: string | null;
  group_name: string | null;
  status: string;
  section: EmailOperationalInboxView;
  next_deadline: EmailInboxDeadline | null;
  proposal_count: number;
  draft_status: string | null;
}

export interface EmailOperationalInboxResponse {
  items: EmailOperationalInboxItem[];
  next_cursor: string | null;
  counts: Record<EmailOperationalInboxView, number>;
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

export interface EmailIntelligenceDetail {
  id: string;
  status: string;
  intent: string | null;
  priority: string | null;
  summary: string | null;
  confidence: number | null;
  needs_attention: boolean;
  human_review_confirmed: boolean;
  linked_group_id: string | null;
  linked_group_name: string | null;
  linked_passenger_ids: string[];
  linked_passengers: Array<{ id: string; name: string }>;
  candidate_links: Array<{
    entity_type: "group" | "passenger";
    entity_id: string;
    name: string;
    confidence: number;
    rationale: string;
    canonical: boolean;
  }>;
  risks: string[];
  missing_information: string[];
  evidence: string[];
  model_version: string;
  schema_version: string;
  completed_at: string | null;
  updated_at: string;
  deadlines: EmailInboxDeadline[];
  proposals: EmailInboxProposal[];
  draft: EmailInboxDraft | null;
}

export interface DecideEmailProposalRequest {
  action: EmailProposalDecisionAction;
  expected_revision: number;
  note?: string;
}

export interface EmailProposalDecisionResponse {
  proposal_id: string;
  status: string;
  revision: number;
  message: string;
}

export interface UpdateEmailReplyDraftRequest {
  subject: string;
  body_text: string;
  expected_revision: number;
}

export type EmailAiFeedbackType =
  | "correction"
  | "confirmation"
  | "dismissal";

export type EmailAiCorrectionField =
  | "summary"
  | "intent"
  | "priority"
  | "linked_group"
  | "linked_passengers"
  | "deadline"
  | "notification";

export interface EmailAiCorrectionValue {
  text?: string;
  intent?: string;
  priority?: "low" | "normal" | "high" | "urgent";
  group_id?: string;
  passenger_ids?: string[];
  deadline_id?: string;
  due_at?: string;
  notification_expected?: boolean;
}

export interface EmailAiFeedbackRequest {
  feedback_type: EmailAiFeedbackType;
  field_name: "analysis" | EmailAiCorrectionField;
  expected_status: "completed" | "review_required" | "ignored";
  expected_updated_at: string;
  correction?: EmailAiCorrectionValue;
  note?: string;
}

export interface EmailAiFeedbackResponse {
  feedback_id: string;
  analysis_id: string;
  created_at: string;
  analysis_status: string;
  analysis_updated_at: string;
}

export interface EmailAiRetryResponse {
  analysis_id: string;
  status: "pending";
  retry_generation: number;
  message: string;
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
  original_email_url: string | null;
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
