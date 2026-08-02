export type GcAppAccountStatus = "invited" | "active" | "suspended" | "deleted";
export type GcAppGroupLifecycle = "active" | "closed" | "archived" | "deleted";
export type GcAppActivationMethod = "invitation" | "temporary_password";
export type GcAppRole = "passenger" | "client_manager" | "coordinator";

export interface GcPage<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
}

export interface GcPageParams {
  page: number;
  page_size: number;
  search?: string;
}

export interface GcCompanyReference {
  id: string;
  name: string;
}

export interface GcAgencyReference {
  id: string;
  name: string;
  email: string;
  is_active: boolean;
}

export interface GcGroupReference {
  id: string;
  name: string;
  lifecycle: GcAppGroupLifecycle;
  destination: string | null;
  start_date: string | null;
  end_date: string | null;
  company: GcCompanyReference | null;
  gc_enabled?: boolean;
}

export interface ClientManagerAccount {
  id: string;
  name: string;
  email: string;
  phone_number: string;
  company: GcCompanyReference;
  assigned_groups: GcGroupReference[];
  status: GcAppAccountStatus;
  force_password_change: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
  revision: number;
  temporary_password?: string | null;
  activation_token?: string | null;
}

export interface ClientManagerFilters extends GcPageParams {
  status?: GcAppAccountStatus | "all";
  company_id?: string;
}

export interface ClientManagerInput {
  name: string;
  email: string;
  phone_number: string;
  company_id: string;
  group_ids: string[];
  force_password_change: boolean;
  activation_method?: GcAppActivationMethod;
  temporary_password?: string;
}

export interface ClientManagerSession {
  id: string;
  device_name: string | null;
  platform: string | null;
  app_version: string | null;
  ip_address: string | null;
  created_at: string;
  last_seen_at: string | null;
  revoked_at: string | null;
  current: boolean;
  status: string;
  expires_at: string | null;
}

export interface GcAuditEvent {
  id: string;
  action: string;
  summary: string;
  actor_name: string | null;
  created_at: string;
}

export interface GcAppVersionMetrics {
  itinerary_version: number;
  common_document_version: number;
  announcement_version: number;
}

export interface GcAppGroupControl extends GcGroupReference {
  gc_app_enabled: boolean;
  passenger_access_enabled: boolean;
  client_manager_access_enabled: boolean;
  coordinator_access_enabled: boolean;
  access_starts_at: string | null;
  access_expires_at: string | null;
  access_revoked_at: string | null;
  revision: number;
  organization_id: string | null;
  active_mobile_users: number;
  synced_device_count: number;
  last_successful_sync_at: string | null;
  versions: GcAppVersionMetrics;
}

export interface GcAppGroupFilters extends GcPageParams {
  lifecycle?: GcAppGroupLifecycle | "all";
}

export interface GcAppControlPatch {
  passenger_access_enabled?: boolean;
  client_manager_access_enabled?: boolean;
  coordinator_access_enabled?: boolean;
  access_starts_at?: string | null;
  access_expires_at?: string | null;
}

export interface ItineraryItemDraft {
  client_id: string;
  time: string;
  title: string;
  description: string;
  location: string;
}

export interface ItineraryDayDraft {
  client_id: string;
  day_number: number;
  date: string;
  title: string;
  items: ItineraryItemDraft[];
}

export interface StructuredItinerary {
  version_id: string | null;
  status: "new" | "draft" | "published" | "retired";
  title: string;
  days: ItineraryDayDraft[];
  draft_revision: string;
  published_version: number;
  published_at: string | null;
  updated_at: string | null;
}

export type GcDocumentCategory =
  | "itinerary_pdf"
  | "travel_tips"
  | "common_instructions"
  | "destination"
  | "emergency"
  | "hotel"
  | "flight_summary"
  | "meeting_point"
  | "dress_code"
  | "baggage"
  | "other";

export interface GcCommonDocument {
  id: string;
  title: string;
  category: GcDocumentCategory;
  filename: string;
  version: number;
  is_published: boolean;
  available_from: string | null;
  available_until: string | null;
  updated_at: string;
  sort_order: number;
}

export interface GcAnnouncement {
  id: string;
  title: string;
  body: string;
  priority: "normal" | "important" | "emergency";
  is_published: boolean;
  available_from: string | null;
  available_until: string | null;
  version: number;
  updated_at: string;
}

export interface GcAppGroupContent {
  itinerary: StructuredItinerary;
  common_documents: GcCommonDocument[];
  announcements: GcAnnouncement[];
}

export interface CommonDocumentUpload {
  file: File;
  title: string;
  category: GcDocumentCategory;
  available_from: string | null;
  available_until: string | null;
  replace_document_id?: string;
}

export interface AnnouncementInput {
  title: string;
  body: string;
  priority: GcAnnouncement["priority"];
  available_from: string | null;
  available_until: string | null;
  publish: boolean;
}
