export type WhatsAppMessageType = "welcome" | "passport_link" | "reminder" | "group_invite" | "update";

export type WhatsAppReminderAudience = "all" | "not_submitted";

export interface WhatsAppMessageDraft {
  message_type: WhatsAppMessageType;
  passport_intro?: string | null;
  passport_link?: string | null;
  group_invite_link?: string | null;
  message_content?: string | null;
  recipient_id?: string | null;
  resend_recipient_id?: string | null;
  header_image_id?: string | null;
  recipient_ids?: string[] | null;
  support_contact_ids?: string[] | null;
  audience?: WhatsAppReminderAudience;
  audience_client_group_id?: string | null;
  update_submission?: "all" | "submitted" | "not_submitted";
  update_distribution?: "all" | "sent" | "pending";
  update_document_type?: string;
  include_previous_recipients?: boolean;
}

export interface WhatsAppPreviewResponse {
  message_type: WhatsAppMessageType;
  template_name: string;
  recipient_id: string;
  recipient_name: string;
  recipient_count: number;
  audience?: WhatsAppReminderAudience;
  audience_client_group_id?: string | null;
  audience_recipient_count?: number;
  /** Full server-resolved audience before the optional explicit selection. */
  audience_recipient_ids?: string[];
  excluded_submitted_count?: number;
  excluded_needs_review_count?: number;
  eligible_recipient_count: number;
  welcome_required_count?: number;
  welcome_required_reason?: string | null;
  already_sent_count: number;
  in_progress_count: number;
  uncertain_recipient_count: number;
  passport_intro: string | null;
  passport_link: string | null;
  group_invite_link?: string | null;
  message_content: string;
  header_image_id: string | null;
  content_source: "default" | "latest_group" | "latest_recipient";
  rendered_message: string;
  header_parameter_values: string[];
  parameter_values: string[];
}

export interface WhatsAppSendResponse {
  batch_id?: string | null;
  audience?: WhatsAppReminderAudience;
  audience_client_group_id?: string | null;
  recipient_count?: number;
  audience_recipient_count?: number;
  excluded_submitted_count?: number;
  excluded_needs_review_count?: number;
  queued: number;
  sent: number;
  failed: number;
  delivery_unknown: number;
  skipped_already_sent: number;
  skipped_in_progress: number;
  skipped_delivery_unknown: number;
  results: Array<{
    recipient_id: string;
    phone_number: string;
    status: string;
    provider_message_id?: string | null;
    error_message?: string | null;
  }>;
}

export interface WhatsAppWelcomeMediaResponse {
  media_id: string;
  file_name: string;
  content_type: string;
}
