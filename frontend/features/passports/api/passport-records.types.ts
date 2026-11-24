import type { PassportSubmission } from "@/types/passport.types";

export type PassportGroupSubmissionFilter =
  | "all"
  | "pending_ai"
  | "ai_approved"
  | "needs_review"
  | "staff_approved"
  | "duplicates"
  | "document_follow_up";

export type PassportGroupSubmissionSort =
  | "name"
  | "updated_at"
  | "verification_confidence";

export interface PassportGroupSubmissionsViewParams {
  search?: string;
  include_deleted?: boolean;
  submission_filter: PassportGroupSubmissionFilter;
  sort_by: PassportGroupSubmissionSort;
  sort_order: "asc" | "desc";
  page: number;
  page_size: number;
}

export interface PassportExpiryAlert {
  submission_id: string;
  client_name: string;
  client_email: string | null;
  passport_number: string | null;
  date_of_expiry: string;
  status: "expired" | "near_expiry";
}

export interface PassportGroupSubmissionsView {
  duplicate_metadata_version?: 2;
  duplicate_clusters?: {
    cluster_id: string;
    total_members: number;
    matching_members: number;
    visible_member_ids: string[];
    first_page: number;
    last_page: number;
  }[];
  items: PassportSubmission[];
  ordered_submission_ids: string[];
  ordered_selection_snapshot: PassportSubmissionSelectionSnapshot[];
  group_total: number;
  document_follow_up_count?: number;
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  returned_count: number;
  cluster_boundaries_preserved: boolean;
  expiry_alerts: PassportExpiryAlert[];
}

export interface BulkDeletePassportSubmissionsResult {
  deleted_count: number;
  deleted_submission_ids: string[];
  deleted_storage_objects: number;
  deleted_notifications: number;
  storage_cleanup_deferred: boolean;
}

export interface PassportSubmissionSelectionSnapshot {
  submission_id: string;
  extraction_revision: number;
}

export interface BulkStaffApproveSkippedSubmission {
  submission_id: string;
  current_status: string;
  reason: "not_completed" | "stale";
  expected_extraction_revision: number;
  current_extraction_revision: number;
}

export interface BulkStaffApprovePassportSelection {
  submission_id: string;
  expected_extraction_revision: number;
}

export interface BulkStaffApprovePassportSubmissionsResult {
  requested_count: number;
  approved_count: number;
  already_approved_count: number;
  skipped_count: number;
  approved_submission_ids: string[];
  already_approved_submission_ids: string[];
  skipped_submissions: BulkStaffApproveSkippedSubmission[];
}

export type PassportReextractOutcome = "completed" | "failed" | "timed_out";

export interface PassportReextractResult {
  submission: PassportSubmission;
  outcome: PassportReextractOutcome;
}

export interface PassportReextractOptions {
  onProgress?: (submission: PassportSubmission) => void;
  timeoutMs?: number;
}
