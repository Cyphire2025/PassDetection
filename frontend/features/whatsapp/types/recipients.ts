import type { RecipientImportPreview, RecipientImportRejectionReasonCode } from '../utils/recipient-import';

export interface WhatsAppRecipientInput {
  name?: string | null;
  phone_number: string;
  imported_fields?: Record<string, string>;
}

export interface WhatsAppRecipientDetailsEdit {
  merged_contact_id: string | null;
  expected_name: string | null;
  expected_imported_fields: Record<string, string>;
  name: string;
  imported_fields: Record<string, string>;
}

export interface WhatsAppSupportContactInput {
  name: string;
  phone_number: string;
}

export interface WhatsAppRecipient {
  id: string;
  name: string | null;
  phone_number: string;
  normalized_phone_number: string;
  imported_fields: Record<string, string>;
  is_source_managed?: boolean;
  merged_contacts?: { id: string; name: string | null; imported_fields: Record<string, string>; }[];
  message_statuses: WhatsAppRecipientMessageStatus[];
  welcome_status?: string | null;
  welcome_delivered?: boolean;
  welcome_required_reason?: string | null;
}

export interface WhatsAppRejectedContactInput {
  source_file_name: string;
  sheet_name: string;
  row_number: number;
  raw_name: string | null;
  raw_phone_number: string | null;
  reason_code: RecipientImportRejectionReasonCode;
  imported_fields?: Record<string, string>;
}

export interface WhatsAppRejectedContact extends WhatsAppRejectedContactInput {
  id: string;
  reason: string;
  created_at: string;
}

export interface WhatsAppReplacedRecipient {
  recipient_id: string;
  resolution_id: string;
  client_group_id: string;
  client_group_name: string;
  name: string | null;
  phone_number: string;
  normalized_phone_number: string;
  imported_fields: Record<string, string>;
  replacement_submission_id: string;
  replacement_name: string;
  replacement_phone: string | null;
  replaced_at: string;
}

export interface WhatsAppUnidentifiedUpload {
  submission_id: string;
  client_group_id: string;
  client_group_name: string;
  name: string;
  phone_number: string | null;
  email: string | null;
  details: Record<string, unknown>;
  updated_at: string;
}

export type WhatsAppRecipientRosterItem =
  | {
    kind: "recipient";
    display_order: number;
    recipient: WhatsAppRecipient;
  }
  | {
    kind: "rejected";
    display_order: number;
    rejected_contact: WhatsAppRejectedContact;
  }
  | {
    kind: "replaced";
    display_order: number;
    replaced_recipient: WhatsAppReplacedRecipient;
  }
  | {
    kind: "unidentified";
    display_order: number;
    unidentified_upload: WhatsAppUnidentifiedUpload;
  };

export interface WhatsAppRecipientRosterResponse {
  items: WhatsAppRecipientRosterItem[];
  counts: {
    all: number;
    sent: number;
    failed: number;
    rejected: number;
    replaced: number;
    unidentified: number;
  };
}

export type WhatsAppContactPreviewResponse = RecipientImportPreview;

export interface WhatsAppRecipientMessageStatus {
  message_type: string;
  status: string;
  already_sent: boolean;
  latest_resend_status: string | null;
  resend_blocked: boolean;
  submitted_at: string | null;
  status_updated_at: string;
}

export interface WhatsAppSupportContact {
  id: string;
  name: string;
  phone_number: string;
  normalized_phone_number: string;
}
