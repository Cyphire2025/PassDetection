import type {
  ClientManagerAccount,
  GcAnnouncement,
  GcAppAvailability,
  GcGroupReference,
  GcPage,
} from "../types";
import type { OwnerBoundRequestConfig } from "@/lib/api/request-owner";

export type GcMutationRequestConfig = Pick<OwnerBoundRequestConfig, "expectedOwnerUserId">;

export type PageEnvelope<T> = GcPage<T> | { items: T[]; total: number; offset: number; limit: number } | T[];

export interface RawClientManager {
  id: string;
  full_name: string;
  email: string;
  phone_number: string;
  organization_id: string;
  organization_name: string;
  status: ClientManagerAccount["status"];
  revision: number;
  group_ids: string[];
  assigned_groups?: RawGroup[];
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
  temporary_password?: string | null;
  activation_token?: string | null;
}

export interface RawClientManagerSession {
  id: string;
  platform: string;
  app_version: string;
  status: string;
  last_seen_at: string | null;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
}

export interface RawAuditEvent {
  id: string;
  action: string;
  actor_email: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
}

export interface RawGroup {
  id: string;
  name: string;
  destination: string | null;
  travel_date: string | null;
  return_date: string | null;
  lifecycle_status: string;
  gc_enabled: boolean;
  client_organization_id?: string | null;
  client_organization_name?: string | null;
  access?: RawGroupAccess | null;
}

export interface RawGroupAccess {
  group_id: string;
  name?: string;
  destination?: string | null;
  travel_date?: string | null;
  return_date?: string | null;
  lifecycle_status?: string;
  client_organization_id?: string | null;
  client_organization_name?: string | null;
  enabled: boolean;
  my_photos_enabled?: boolean;
  passenger_access_enabled: boolean;
  client_manager_access_enabled: boolean;
  coordinator_access_enabled: boolean;
  access_starts_at: string | null;
  access_expires_at: string | null;
  revoked_at: string | null;
  removed_at?: string | null;
  itinerary_version: number;
  common_document_version: number;
  announcement_version: number;
  revision: number;
  last_successful_sync_at: string | null;
  active_mobile_users?: number;
  synced_device_count?: number;
  app_availability?: GcAppAvailability;
  app_availability_reason?: GcGroupReference["app_availability_reason"];
  app_availability_evaluated_at?: string;
}

export interface RawItineraryItem {
  title: string;
  description: string | null;
  starts_at: string | null;
  ends_at: string | null;
  location_name: string | null;
  latitude: number | null;
  longitude: number | null;
  sort_order: number;
}

export interface RawItineraryVersion {
  id: string;
  group_id: string;
  version: number;
  status: "draft" | "published" | "retired";
  title: string;
  published_at: string | null;
  created_at: string;
  updated_at: string;
  days: {
    day_number: number;
    date: string | null;
    title: string | null;
    items: RawItineraryItem[];
  }[];
}

export interface RawCommonDocument {
  id: string;
  category: string;
  display_name: string;
  original_filename: string;
  version: number;
  status: "draft" | "published" | "retired" | "revoked";
  sort_order: number;
  available_from: string | null;
  available_until: string | null;
  updated_at: string;
}

export interface RawAnnouncement {
  id: string;
  title: string;
  message: string;
  priority: GcAnnouncement["priority"];
  status: "draft" | "published" | "retired" | "revoked";
  version: number;
  available_from: string | null;
  available_until: string | null;
  updated_at: string;
}
