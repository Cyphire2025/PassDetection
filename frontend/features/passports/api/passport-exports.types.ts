export type PassportGroupExportKind = "passport_images" | "passport_excel";

export type PassportGroupExportMode = "all" | "incremental";

export interface PassportGroupExportHistoryItem {
  id: string;
  export_kind: PassportGroupExportKind;
  export_mode: PassportGroupExportMode;
  baseline_export_id: string | null;
  total_available_count: number;
  exported_count: number;
  pending_recipient_count: number;
  new_submission_count: number;
  changed_submission_count?: number;
  removed_submission_count?: number;
  compatible: boolean;
  actor_email: string | null;
  created_at: string;
  completed_at: string;
}

export interface PassportGroupExportHistory {
  group_id: string;
  export_kind: PassportGroupExportKind;
  current_submission_count: number;
  items: PassportGroupExportHistoryItem[];
  page: number;
  page_size: number;
  total_count: number;
  total_pages: number;
}

export interface PassportGroupExportHistorySubmission {
  submission_id: string;
  record_available: boolean;
  client_name: string | null;
  client_phone: string | null;
  client_email: string | null;
  passport_number: string | null;
}

export interface PassportGroupExportHistoryDetail {
  history_id: string;
  group_id: string;
  export_kind: PassportGroupExportKind;
  created_at: string;
  completed_at: string;
  exported_count: number;
  items: PassportGroupExportHistorySubmission[];
  page: number;
  page_size: number;
  total_pages: number;
}

export interface PassportGroupExportRequest {
  groupId: string;
  groupName?: string;
  mode: PassportGroupExportMode;
  baselineExportId?: string;
  requestId?: string;
  supplementalFields?: string[];
  groupByField?: string;
  agencyMatchField?: string;
}

export type PassportWhatsAppTrackingStatus =
  | "all"
  | "submitted"
  | "not_submitted"
  | "multiple_submissions"
  | "needs_review"
  | "unmatched_submission"
  | "replacement"
  | "rejected_upload";

export interface PassportWhatsAppTrackingExportRequest {
  groupId: string;
  status: PassportWhatsAppTrackingStatus;
  broadcastId?: string;
}

export interface PassportGroupExportFieldOption {
  key: string;
  label: string;
  source: "whatsapp";
  selected_by_default: boolean;
}

export interface PassportGroupExportGroupingOption {
  key: string;
  label: string;
  fixed: boolean;
}

export interface PassportExcelFieldOptions {
  fields: PassportGroupExportFieldOption[];
  grouping_fields: PassportGroupExportGroupingOption[];
  default_selected_fields: string[];
  default_group_by_field: string | null;
}

export interface PassportGroupExportFieldOptions extends PassportExcelFieldOptions {
  group_id: string;
  agency_match_enabled: boolean;
  agency_match_fields: PassportGroupExportFieldOption[];
}

export interface PassportSelectedGroupsExportFieldOptions extends PassportExcelFieldOptions {
  group_ids: string[];
}

export interface PassportSelectedGroupsExportRequest {
  groupIds: string[];
  supplementalFields: string[];
  groupByField: string;
}

export interface PassportSelectedImagesExportRequest {
  groupId: string;
  groupName?: string;
  submissionIds: string[];
}

export interface PassportGroupExportCompletion {
  history_id: string;
  group_id: string;
  export_kind: PassportGroupExportKind;
  status: "completed";
  completed_at: string;
}
