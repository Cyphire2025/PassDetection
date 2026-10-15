import type { CursorPage } from "../types";

export interface CompanyPerson {
  id: string;
  display_name: string;
  status: string;
  revision: number;
  trip_count: number;
  document_version_count: number;
  submission_count: number;
  latest_submission_at?: string | null;
  duplicate_status: "none" | "possible";
  current_passport_last4: string | null;
}

export interface CompanyCurrentDocument {
  id: string;
  passport_id: string;
  revision_number: number;
  fields: Record<string, string>;
  issuing_country: string;
  document_type: string;
}

export interface CompanyPersonRecord {
  id: string;
  status: string;
  display_name: string;
  revision: number;
  contact_revision: number;
  phone_number: string | null;
  phone_verified: boolean;
  current_document: CompanyCurrentDocument | null;
  original_record?: CompanyOriginalRecord | null;
}

export interface CompanyOriginalRecord {
  source_id: string;
  group_id: string;
  status: string;
  source_revision: number;
  created_at: string;
  fields: Record<string, string>;
}

export interface CompanyPersonEdit {
  expected_revision: number;
  idempotency_key: string;
  reason: string;
  display_name: string;
  phone_number: string | null;
  fields?: Record<string, string>;
}

export interface CompanyDocumentAsset {
  id: string;
  side: string;
  content_type: string;
  byte_size: number;
  availability: string;
}

export interface CompanyDocumentVersion {
  id: string;
  passport_id: string;
  revision_number: number;
  status: string;
  created_at: string;
  change_kind: string;
  is_current: boolean;
  fields: Record<string, string>;
  assets: CompanyDocumentAsset[];
}

export interface CompanyDocumentUpload {
  expected_revision: number;
  idempotency_key: string;
  reason: string;
  change_kind: "scan" | "renewal" | "correction";
  side: "front" | "back" | "cover" | "back_cover" | "photo";
  issuing_country: string;
  document_type: string;
  fields: Record<string, string>;
}

export type CompanyPeoplePage = CursorPage<CompanyPerson> & { indexing_pending?: boolean; indexing_failed?: boolean };
export type CompanyPeopleSort = "newest" | "name_asc" | "name_desc";
export type CompanySubmissionFilter = "all" | "one" | "multiple";
export interface CompanyPeopleSearch { search: string; cursor?: string; sort?: CompanyPeopleSort; submissions?: CompanySubmissionFilter }
export type CompanyDocumentPage = CursorPage<CompanyDocumentVersion>;
export interface CompanyOriginalDocument { id: string; group_id: string; group_name: string; created_at: string; revision_number: number; available_sides: string[] }
