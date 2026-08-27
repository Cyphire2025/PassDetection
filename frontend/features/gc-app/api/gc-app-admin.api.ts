import apiClient from "@/lib/api/client";
import type {
  AnnouncementInput,
  ClientManagerAccount,
  ClientManagerFilters,
  ClientManagerInput,
  ClientManagerSession,
  CommonDocumentUpload,
  GcAnnouncement,
  GcAgencyReference,
  GcAppAccountStatus,
  GcAppControlPatch,
  GcAppGroupContent,
  GcAppGroupControl,
  GcAppGroupFilters,
  GcAuditEvent,
  GcCommonDocument,
  GcCompanyReference,
  GcGroupReference,
  GcPage,
  GcPageParams,
  StructuredItinerary,
} from "../types";

const ROOT = "/api/v1/gc-app/admin";
const PAGE_SIZE = 20;
const AGENCY_DIRECTORY_PAGE_SIZE = 100;
const MAX_AGENCY_DIRECTORY_ITEMS = 5_000;

type PageEnvelope<T> = GcPage<T> | { items: T[]; total: number; offset: number; limit: number } | T[];

interface RawClientManager {
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

interface RawClientManagerSession {
  id: string;
  platform: string;
  app_version: string;
  status: string;
  last_seen_at: string | null;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
}

interface RawAuditEvent {
  id: string;
  action: string;
  actor_email: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
}

interface RawGroup {
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

interface RawGroupAccess {
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
  itinerary_version: number;
  common_document_version: number;
  announcement_version: number;
  revision: number;
  last_successful_sync_at: string | null;
  active_mobile_users?: number;
  synced_device_count?: number;
}

interface RawItineraryItem {
  title: string;
  description: string | null;
  starts_at: string | null;
  ends_at: string | null;
  location_name: string | null;
  latitude: number | null;
  longitude: number | null;
  sort_order: number;
}

interface RawItineraryVersion {
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

interface RawCommonDocument {
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

interface RawAnnouncement {
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

function asPage<T>(data: PageEnvelope<T>, params: GcPageParams): GcPage<T> {
  if (Array.isArray(data)) {
    return {
      items: data,
      total: data.length,
      page: params.page,
      page_size: params.page_size,
      has_next: data.length === params.page_size,
    };
  }
  if ("offset" in data) {
    return {
      items: data.items,
      total: data.total,
      page: Math.floor(data.offset / data.limit) + 1,
      page_size: data.limit,
      has_next: data.offset + data.items.length < data.total,
    };
  }
  return data;
}

function toOffsetParams(params: GcPageParams) {
  return {
    q: params.search || undefined,
    offset: (params.page - 1) * params.page_size,
    limit: params.page_size,
  };
}

function agencyParams(agencyId: string | null, extra: Record<string, unknown> = {}) {
  return { ...extra, agency_id: agencyId ?? undefined };
}

function normalizeGroup(group: RawGroup): GcGroupReference {
  const lifecycle = ["active", "closed", "archived", "deleted"].includes(group.lifecycle_status)
    ? group.lifecycle_status as GcGroupReference["lifecycle"]
    : "archived";
  return {
    id: group.id,
    name: group.name,
    lifecycle,
    destination: group.destination,
    start_date: group.travel_date,
    end_date: group.return_date,
    company: group.client_organization_id && group.client_organization_name ? {
      id: group.client_organization_id,
      name: group.client_organization_name,
    } : null,
    gc_enabled: group.gc_enabled,
    gc_revision: group.access?.revision,
  };
}

function normalizeClientManager(manager: RawClientManager): ClientManagerAccount {
  return {
    id: manager.id,
    name: manager.full_name,
    email: manager.email,
    phone_number: manager.phone_number,
    company: { id: manager.organization_id, name: manager.organization_name },
    assigned_groups: manager.assigned_groups?.map(normalizeGroup) ?? manager.group_ids.map((id) => ({
      id,
      name: "Assigned group",
      lifecycle: "active",
      destination: null,
      start_date: null,
      end_date: null,
      company: { id: manager.organization_id, name: manager.organization_name },
      gc_enabled: true,
    })),
    status: manager.status,
    last_login_at: manager.last_login_at,
    created_at: manager.created_at,
    updated_at: manager.updated_at,
    revision: manager.revision,
    temporary_password: manager.temporary_password,
    activation_token: manager.activation_token,
  };
}

function normalizeControl(access: RawGroupAccess, group?: RawGroup): GcAppGroupControl {
  const reference = group ? normalizeGroup(group) : null;
  const lifecycleValue = access.lifecycle_status ?? reference?.lifecycle ?? "active";
  const lifecycle = ["active", "closed", "archived", "deleted"].includes(lifecycleValue)
    ? lifecycleValue as GcAppGroupControl["lifecycle"]
    : "archived";
  const organizationId = access.client_organization_id ?? reference?.company?.id ?? null;
  const organizationName = access.client_organization_name ?? reference?.company?.name ?? null;
  return {
    id: access.group_id,
    name: access.name ?? reference?.name ?? "GC App group",
    lifecycle,
    destination: access.destination ?? reference?.destination ?? null,
    start_date: access.travel_date ?? reference?.start_date ?? null,
    end_date: access.return_date ?? reference?.end_date ?? null,
    company: organizationId && organizationName ? { id: organizationId, name: organizationName } : null,
    gc_enabled: access.enabled,
    gc_app_enabled: access.enabled,
    my_photos_enabled: access.my_photos_enabled ?? false,
    passenger_access_enabled: access.passenger_access_enabled,
    client_manager_access_enabled: access.client_manager_access_enabled,
    coordinator_access_enabled: access.coordinator_access_enabled,
    access_starts_at: access.access_starts_at,
    access_expires_at: access.access_expires_at,
    access_revoked_at: access.revoked_at,
    revision: access.revision,
    organization_id: organizationId,
    active_mobile_users: access.active_mobile_users ?? 0,
    synced_device_count: access.synced_device_count ?? 0,
    last_successful_sync_at: access.last_successful_sync_at,
    versions: {
      itinerary_version: access.itinerary_version,
      common_document_version: access.common_document_version,
      announcement_version: access.announcement_version,
    },
  };
}

function fullControlBody(control: GcAppGroupControl, patch: GcAppControlPatch, enabled = control.gc_app_enabled) {
  if (!control.organization_id) {
    throw new Error("The GC App group is missing its client organization. Refresh before changing access.");
  }
  return {
    client_organization_id: control.organization_id,
    enabled,
    passenger_access_enabled: patch.passenger_access_enabled ?? control.passenger_access_enabled,
    client_manager_access_enabled: patch.client_manager_access_enabled ?? control.client_manager_access_enabled,
    coordinator_access_enabled: patch.coordinator_access_enabled ?? control.coordinator_access_enabled,
    access_starts_at: patch.access_starts_at === undefined ? control.access_starts_at : patch.access_starts_at,
    access_expires_at: patch.access_expires_at === undefined ? control.access_expires_at : patch.access_expires_at,
    expected_revision: control.revision,
  };
}

function normalizeItinerary(raw: RawItineraryVersion | null): StructuredItinerary {
  if (!raw) {
    return {
      version_id: null,
      status: "new",
      title: "Group itinerary",
      days: [],
      draft_revision: "new",
      published_version: 0,
      published_at: null,
      updated_at: null,
    };
  }
  return {
    version_id: raw.id,
    status: raw.status,
    title: raw.title,
    days: raw.days.map((day, dayIndex) => ({
      client_id: `day-${day.day_number}-${dayIndex}`,
      day_number: day.day_number,
      date: day.date ?? "",
      title: day.title ?? `Day ${day.day_number}`,
      items: [...day.items].sort((a, b) => a.sort_order - b.sort_order).map((item, itemIndex) => ({
        client_id: `item-${day.day_number}-${item.sort_order}-${itemIndex}`,
        time: itineraryTime(item.starts_at),
        title: item.title,
        description: item.description ?? "",
        location: item.location_name ?? "",
      })),
    })),
    draft_revision: raw.id,
    published_version: raw.version,
    published_at: raw.published_at,
    updated_at: raw.updated_at,
  };
}

function itineraryTime(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function itineraryStartsAt(dayDate: string, time: string): string | null {
  if (!dayDate || !time) return null;
  const date = new Date(`${dayDate}T${time}:00`);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function normalizeDocument(raw: RawCommonDocument): GcCommonDocument {
  return {
    id: raw.id,
    title: raw.display_name,
    category: raw.category as GcCommonDocument["category"],
    filename: raw.original_filename,
    version: raw.version,
    is_published: raw.status === "published",
    available_from: raw.available_from,
    available_until: raw.available_until,
    updated_at: raw.updated_at,
    sort_order: raw.sort_order,
  };
}

function normalizeAnnouncement(raw: RawAnnouncement): GcAnnouncement {
  return {
    id: raw.id,
    title: raw.title,
    body: raw.message,
    priority: raw.priority,
    is_published: raw.status === "published",
    available_from: raw.available_from,
    available_until: raw.available_until,
    version: raw.version,
    updated_at: raw.updated_at,
  };
}

async function mapBounded<T, R>(items: T[], limit: number, mapper: (item: T) => Promise<R>): Promise<R[]> {
  const output = new Array<R>(items.length);
  let cursor = 0;
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor++;
      output[index] = await mapper(items[index]);
    }
  }));
  return output;
}

export const gcAppAdminApi = {
  listAgencies: async (signal?: AbortSignal): Promise<GcAgencyReference[]> => {
    type AgencyPage = {
      items: GcAgencyReference[];
      total: number;
      offset: number;
      limit: number;
    };
    const { data: first } = await apiClient.get<AgencyPage>(`${ROOT}/agencies`, {
      params: { offset: 0, limit: AGENCY_DIRECTORY_PAGE_SIZE },
      signal,
    });
    if (first.total > MAX_AGENCY_DIRECTORY_ITEMS) {
      throw new Error(
        "The agency directory is too large to load safely. Use an agency search before continuing.",
      );
    }
    const offsets = Array.from(
      { length: Math.max(0, Math.ceil(first.total / first.limit) - 1) },
      (_value, index) => (index + 1) * first.limit,
    );
    const remaining = await mapBounded(offsets, 4, async (offset) => {
      const { data } = await apiClient.get<AgencyPage>(`${ROOT}/agencies`, {
        params: { offset, limit: first.limit },
        signal,
      });
      return data.items;
    });
    return [...first.items, ...remaining.flat()]
      .filter((agency) => agency.is_active)
      .slice(0, first.total);
  },

  listClientManagers: async (
    agencyId: string | null,
    params: ClientManagerFilters,
    signal?: AbortSignal,
  ): Promise<GcPage<ClientManagerAccount>> => {
    const { data } = await apiClient.get<PageEnvelope<RawClientManager>>(
      `${ROOT}/client-managers`,
      {
        params: {
          ...toOffsetParams(params),
          agency_id: agencyId ?? undefined,
          status: params.status === "all" ? undefined : params.status,
          company_id: params.company_id || undefined,
        },
        signal,
      },
    );
    const page = asPage(data, params);
    return { ...page, items: page.items.map(normalizeClientManager) };
  },

  createClientManager: async (agencyId: string | null, body: ClientManagerInput): Promise<ClientManagerAccount> => {
    const { data } = await apiClient.post<RawClientManager>(`${ROOT}/client-managers`, {
      full_name: body.name,
      email: body.email,
      phone_number: body.phone_number,
      organization_id: body.company_id,
      group_ids: body.group_ids,
      return_temporary_password_once: false,
      invitation_flow: true,
      return_activation_token_once: true,
      force_password_change: false,
    }, { params: { agency_id: agencyId ?? undefined } });
    return normalizeClientManager(data);
  },

  updateClientManager: async (
    agencyId: string | null,
    managerId: string,
    current: ClientManagerAccount,
    body: ClientManagerInput,
  ): Promise<ClientManagerAccount> => {
    const { data: updatedProfile } = await apiClient.patch<RawClientManager>(
      `${ROOT}/client-managers/${managerId}`,
      {
        full_name: body.name,
        email: body.email,
        phone_number: body.phone_number,
        organization_id: body.company_id,
        expected_revision: current.revision,
      },
      { params: agencyParams(agencyId) },
    );
    const { data: updatedGroups } = await apiClient.put<RawClientManager>(
      `${ROOT}/client-managers/${managerId}/groups`,
      { group_ids: body.group_ids, expected_revision: updatedProfile.revision },
      { params: agencyParams(agencyId) },
    );
    return normalizeClientManager(updatedGroups);
  },

  setClientManagerStatus: async (
    agencyId: string | null,
    managerId: string,
    status: Exclude<GcAppAccountStatus, "deleted" | "invited">,
    revision: number,
  ): Promise<ClientManagerAccount> => {
    const { data } = await apiClient.patch<RawClientManager>(
      `${ROOT}/client-managers/${managerId}/status`,
      { status, expected_revision: revision },
      { params: agencyParams(agencyId) },
    );
    return normalizeClientManager(data);
  },

  resetClientManagerPassword: async (
    agencyId: string | null,
    managerId: string,
  ): Promise<ClientManagerAccount> => {
    const { data } = await apiClient.post<RawClientManager>(
      `${ROOT}/client-managers/${managerId}/reset-password`,
      { issue_activation_link: true },
      { params: agencyParams(agencyId) },
    );
    return normalizeClientManager(data);
  },

  revokeClientManagerSessions: async (agencyId: string | null, managerId: string): Promise<void> => {
    await apiClient.post(
      `${ROOT}/client-managers/${managerId}/revoke-sessions`,
      undefined,
      { params: agencyParams(agencyId) },
    );
  },

  softDeleteClientManager: async (agencyId: string | null, managerId: string): Promise<void> => {
    await apiClient.delete(`${ROOT}/client-managers/${managerId}`, {
      params: agencyParams(agencyId),
    });
  },

  listClientManagerSessions: async (
    agencyId: string | null,
    managerId: string,
    params: GcPageParams,
    signal?: AbortSignal,
  ): Promise<GcPage<ClientManagerSession>> => {
    const { data } = await apiClient.get<PageEnvelope<RawClientManagerSession>>(
      `${ROOT}/client-managers/${managerId}/sessions`,
      { params: agencyParams(agencyId, toOffsetParams(params)), signal },
    );
    const page = asPage(data, params);
    return { ...page, items: page.items.map((session) => ({
      id: session.id,
      device_name: null,
      platform: session.platform,
      app_version: session.app_version,
      ip_address: null,
      created_at: session.created_at,
      last_seen_at: session.last_seen_at,
      revoked_at: session.revoked_at,
      current: session.status === "active",
      status: session.status,
      expires_at: session.expires_at,
    })) };
  },

  listClientManagerAudit: async (
    agencyId: string | null,
    managerId: string,
    params: GcPageParams,
    signal?: AbortSignal,
  ): Promise<GcPage<GcAuditEvent>> => {
    const { data } = await apiClient.get<PageEnvelope<RawAuditEvent>>(
      `${ROOT}/client-managers/${managerId}/audit`,
      { params: agencyParams(agencyId, toOffsetParams(params)), signal },
    );
    const page = asPage(data, params);
    return { ...page, items: page.items.map((event) => ({
      id: event.id,
      action: event.action,
      summary: event.action.replaceAll("_", " ").replaceAll(".", " / "),
      actor_name: event.actor_email,
      created_at: event.created_at,
    })) };
  },

  searchCompanies: async (
    agencyId: string | null,
    params: GcPageParams,
    signal?: AbortSignal,
  ): Promise<GcPage<GcCompanyReference>> => {
    const { data } = await apiClient.get<PageEnvelope<GcCompanyReference>>(
      `${ROOT}/client-organizations/search`,
      {
        params: {
          ...toOffsetParams(params),
          agency_id: agencyId ?? undefined,
        },
        signal,
      },
    );
    return asPage(data, params);
  },

  createClientOrganization: async (
    agencyId: string | null,
    name: string,
  ): Promise<GcCompanyReference> => {
    const { data } = await apiClient.post<GcCompanyReference>(
      `${ROOT}/client-organizations`,
      { name },
      { params: agencyParams(agencyId) },
    );
    return data;
  },

  removeClientOrganization: async (
    agencyId: string | null,
    organizationId: string,
  ): Promise<void> => {
    await apiClient.delete(`${ROOT}/client-organizations/${organizationId}`, {
      params: agencyParams(agencyId),
    });
  },

  searchGroups: async (
    agencyId: string | null,
    params: GcPageParams & { eligible_only?: boolean },
    signal?: AbortSignal,
  ): Promise<GcPage<GcGroupReference>> => {
    const { data } = await apiClient.get<PageEnvelope<RawGroup>>(
      `${ROOT}/groups`,
      {
        params: {
          ...toOffsetParams(params),
          agency_id: agencyId ?? undefined,
          eligible_only: params.eligible_only || undefined,
        },
        signal,
      },
    );
    const page = asPage(data, params);
    return { ...page, items: page.items.map(normalizeGroup) };
  },

  listGroups: async (
    agencyId: string | null,
    params: GcAppGroupFilters,
    signal?: AbortSignal,
  ): Promise<GcPage<GcAppGroupControl>> => {
    const { data } = await apiClient.get<PageEnvelope<RawGroup>>(`${ROOT}/groups`, {
      params: {
        ...toOffsetParams(params),
        agency_id: agencyId ?? undefined,
        gc_enabled: true,
        lifecycle_status: params.lifecycle === "all" ? undefined : params.lifecycle,
      },
      signal,
    });
    const page = asPage(data, params);
    const enabledGroups = page.items.filter((group) => group.gc_enabled);
    const items = await mapBounded(enabledGroups, 4, async (group) => {
      if (group.access) return normalizeControl(group.access, group);
      const response = await apiClient.get<RawGroupAccess>(`${ROOT}/groups/${group.id}`, {
        params: agencyParams(agencyId),
        signal,
      });
      return normalizeControl(response.data, group);
    });
    return { ...page, items, total: enabledGroups.length === page.items.length ? page.total : items.length, has_next: enabledGroups.length === page.items.length ? page.has_next : false };
  },

  getGroupControl: async (
    agencyId: string | null,
    groupId: string,
    signal?: AbortSignal,
  ): Promise<GcAppGroupControl> => {
    const { data } = await apiClient.get<RawGroupAccess>(`${ROOT}/groups/${groupId}`, {
      params: agencyParams(agencyId),
      signal,
    });
    return normalizeControl(data);
  },

  addGroup: async (
    agencyId: string | null,
    group: GcGroupReference,
    company: GcCompanyReference,
  ): Promise<GcAppGroupControl> => {
    const { data } = await apiClient.put<RawGroupAccess>(`${ROOT}/groups/${group.id}`, {
      client_organization_id: company.id,
      enabled: true,
      passenger_access_enabled: true,
      client_manager_access_enabled: true,
      coordinator_access_enabled: true,
      access_starts_at: null,
      access_expires_at: null,
      expected_revision: group.gc_revision ?? null,
    }, { params: agencyParams(agencyId) });
    const normalized = normalizeControl(data, {
      id: group.id,
      name: group.name,
      destination: group.destination,
      travel_date: group.start_date,
      return_date: group.end_date,
      lifecycle_status: group.lifecycle,
      gc_enabled: true,
      client_organization_id: company.id,
      client_organization_name: company.name,
    });
    return { ...normalized, organization_id: company.id, company };
  },

  removeGroup: async (agencyId: string | null, control: GcAppGroupControl): Promise<void> => {
    await apiClient.put(
      `${ROOT}/groups/${control.id}`,
      fullControlBody(control, {
        passenger_access_enabled: false,
        client_manager_access_enabled: false,
        coordinator_access_enabled: false,
      }, false),
      { params: agencyParams(agencyId) },
    );
  },

  updateGroupControl: async (
    agencyId: string | null,
    control: GcAppGroupControl,
    patch: GcAppControlPatch,
  ): Promise<GcAppGroupControl> => {
    const { data } = await apiClient.put<RawGroupAccess>(
      `${ROOT}/groups/${control.id}`,
      fullControlBody(control, patch),
      { params: agencyParams(agencyId) },
    );
    return normalizeControl(data, {
      id: control.id,
      name: control.name,
      destination: control.destination,
      travel_date: control.start_date,
      return_date: control.end_date,
      lifecycle_status: control.lifecycle,
      gc_enabled: data.enabled,
      client_organization_id: control.organization_id,
      client_organization_name: control.company?.name ?? null,
    });
  },

  setMyPhotosEnabled: async (
    agencyId: string | null,
    control: GcAppGroupControl,
    enabled: boolean,
  ): Promise<GcAppGroupControl> => {
    const { data } = await apiClient.put<RawGroupAccess>(
      `${ROOT}/groups/${control.id}/features/my-photos`,
      { enabled, expected_revision: control.revision },
      { params: agencyParams(agencyId) },
    );
    return normalizeControl(data, {
      id: control.id,
      name: control.name,
      destination: control.destination,
      travel_date: control.start_date,
      return_date: control.end_date,
      lifecycle_status: control.lifecycle,
      gc_enabled: data.enabled,
      client_organization_id: control.organization_id,
      client_organization_name: control.company?.name ?? null,
    });
  },

  revokeGroupAccess: async (agencyId: string | null, groupId: string): Promise<void> => {
    await apiClient.delete(`${ROOT}/groups/${groupId}`, { params: agencyParams(agencyId) });
  },

  getGroupContent: async (
    agencyId: string | null,
    groupId: string,
    signal?: AbortSignal,
  ): Promise<GcAppGroupContent> => {
    const [documents, announcements] = await Promise.all([
      apiClient.get<RawCommonDocument[]>(`${ROOT}/groups/${groupId}/common-documents`, {
        params: agencyParams(agencyId),
        signal,
      }),
      apiClient.get<RawAnnouncement[]>(`${ROOT}/groups/${groupId}/announcements`, {
        params: agencyParams(agencyId),
        signal,
      }),
    ]);
    return {
      common_documents: documents.data.map(normalizeDocument),
      announcements: announcements.data.map(normalizeAnnouncement),
    };
  },

  saveItineraryDraft: async (
    agencyId: string | null,
    groupId: string,
    itinerary: StructuredItinerary,
    expectedAccessRevision: number,
  ): Promise<StructuredItinerary> => {
    const { data } = await apiClient.post<RawItineraryVersion>(
      `${ROOT}/groups/${groupId}/itineraries/drafts`,
      {
        title: itinerary.title,
        days: itinerary.days.map((day, dayIndex) => ({
          day_number: dayIndex + 1,
          date: day.date || null,
          title: day.title || null,
          items: day.items.map((item, itemIndex) => ({
            title: item.title,
            description: item.description || null,
            starts_at: itineraryStartsAt(day.date, item.time),
            ends_at: null,
            location_name: item.location || null,
            latitude: null,
            longitude: null,
            sort_order: itemIndex,
          })),
        })),
        expected_access_revision: expectedAccessRevision,
      },
      { params: agencyParams(agencyId) },
    );
    return normalizeItinerary(data);
  },

  publishItinerary: async (
    agencyId: string | null,
    groupId: string,
    versionId: string,
  ): Promise<StructuredItinerary> => {
    const { data } = await apiClient.post<RawItineraryVersion>(
      `${ROOT}/groups/${groupId}/itineraries/${versionId}/publish`,
      undefined,
      { params: agencyParams(agencyId) },
    );
    return normalizeItinerary(data);
  },

  unpublishItinerary: async (
    agencyId: string | null,
    groupId: string,
    versionId: string,
  ): Promise<StructuredItinerary> => {
    const { data } = await apiClient.post<RawItineraryVersion>(
      `${ROOT}/groups/${groupId}/itineraries/${versionId}/unpublish`,
      undefined,
      { params: agencyParams(agencyId) },
    );
    return normalizeItinerary(data);
  },

  uploadCommonDocument: async (
    agencyId: string | null,
    groupId: string,
    upload: CommonDocumentUpload,
    expectedAccessRevision: number,
  ): Promise<GcCommonDocument> => {
    const form = new FormData();
    form.append("file", upload.file);
    form.append("display_name", upload.title);
    form.append("category", upload.category);
    form.append("offline_available", "true");
    form.append("expected_access_revision", String(expectedAccessRevision));
    const endpoint = upload.replace_document_id
      ? `${ROOT}/groups/${groupId}/common-documents/${upload.replace_document_id}/replace`
      : `${ROOT}/groups/${groupId}/common-documents`;
    const { data } = await apiClient.post<RawCommonDocument>(
      endpoint,
      form,
      {
        params: agencyParams(agencyId),
        // Let the browser generate the multipart boundary. Supplying a bare
        // multipart Content-Type can produce an unparseable or indefinitely
        // pending upload because the boundary is part of that header. The
        // shared API client defaults to JSON, so explicitly clear that default
        // for this FormData request.
        headers: { "Content-Type": null },
        timeout: 120_000,
        onUploadProgress: (event) => {
          const ratio = event.progress
            ?? (event.total && event.total > 0 ? event.loaded / event.total : null);
          if (ratio !== null) {
            upload.onProgress?.(Math.min(100, Math.max(0, Math.round(ratio * 100))));
          }
        },
      },
    );
    return normalizeDocument(data);
  },

  setCommonDocumentPublished: async (
    agencyId: string | null,
    groupId: string,
    documentId: string,
    published: boolean,
  ): Promise<GcCommonDocument> => {
    const { data } = await apiClient.post<RawCommonDocument>(
      `${ROOT}/groups/${groupId}/common-documents/${documentId}/${published ? "publish" : "unpublish"}`,
      undefined,
      { params: agencyParams(agencyId) },
    );
    return normalizeDocument(data);
  },

  previewCommonDocument: async (
    agencyId: string | null,
    groupId: string,
    documentId: string,
    signal?: AbortSignal,
  ): Promise<Blob> => {
    const { data } = await apiClient.get<Blob>(
      `${ROOT}/groups/${groupId}/common-documents/${documentId}/content`,
      {
        params: agencyParams(agencyId),
        responseType: "blob",
        signal,
        timeout: 120_000,
      },
    );
    if (!(data instanceof Blob) || data.type.split(";", 1)[0]?.toLowerCase() !== "application/pdf") {
      throw new Error("The common document preview was not a PDF.");
    }
    return data;
  },

  reorderCommonDocuments: async (
    agencyId: string | null,
    groupId: string,
    orderedDocumentIds: string[],
    expectedAccessRevision: number,
  ): Promise<GcCommonDocument[]> => {
    const { data } = await apiClient.put<RawCommonDocument[]>(
      `${ROOT}/groups/${groupId}/common-documents/reorder`,
      { ordered_document_ids: orderedDocumentIds, expected_access_revision: expectedAccessRevision },
      { params: agencyParams(agencyId) },
    );
    return data.map(normalizeDocument);
  },

  deleteCommonDocument: async (
    agencyId: string | null,
    groupId: string,
    documentId: string,
  ): Promise<void> => {
    await apiClient.delete(`${ROOT}/groups/${groupId}/common-documents/${documentId}`, {
      params: agencyParams(agencyId),
    });
  },

  createAnnouncement: async (
    agencyId: string | null,
    groupId: string,
    body: AnnouncementInput,
    expectedAccessRevision: number,
  ): Promise<GcAnnouncement> => {
    const { data } = await apiClient.post<RawAnnouncement>(
      `${ROOT}/groups/${groupId}/announcements`,
      {
        title: body.title,
        message: body.body,
        priority: body.priority,
        available_from: body.available_from,
        available_until: body.available_until,
        expected_access_revision: expectedAccessRevision,
      },
      { params: agencyParams(agencyId) },
    );
    if (!body.publish) return normalizeAnnouncement(data);
    const published = await apiClient.post<RawAnnouncement>(
      `${ROOT}/groups/${groupId}/announcements/${data.id}/publish`,
      undefined,
      { params: agencyParams(agencyId) },
    );
    return normalizeAnnouncement(published.data);
  },

  updateAnnouncement: async (
    agencyId: string | null,
    groupId: string,
    announcementId: string,
    body: AnnouncementInput,
    expectedAccessRevision: number,
  ): Promise<GcAnnouncement> => {
    const { data } = await apiClient.put<RawAnnouncement>(
      `${ROOT}/groups/${groupId}/announcements/${announcementId}`,
      {
        title: body.title,
        message: body.body,
        priority: body.priority,
        available_from: body.available_from,
        available_until: body.available_until,
        expected_access_revision: expectedAccessRevision,
      },
      { params: agencyParams(agencyId) },
    );
    if (!body.publish) return normalizeAnnouncement(data);
    const published = await apiClient.post<RawAnnouncement>(
      `${ROOT}/groups/${groupId}/announcements/${data.id}/publish`,
      undefined,
      { params: agencyParams(agencyId) },
    );
    return normalizeAnnouncement(published.data);
  },

  setAnnouncementPublished: async (
    agencyId: string | null,
    groupId: string,
    announcementId: string,
    published: boolean,
  ): Promise<GcAnnouncement> => {
    const { data } = await apiClient.post<RawAnnouncement>(
      `${ROOT}/groups/${groupId}/announcements/${announcementId}/${published ? "publish" : "unpublish"}`,
      undefined,
      { params: agencyParams(agencyId) },
    );
    return normalizeAnnouncement(data);
  },

  deleteAnnouncement: async (
    agencyId: string | null,
    groupId: string,
    announcementId: string,
  ): Promise<void> => {
    await apiClient.delete(`${ROOT}/groups/${groupId}/announcements/${announcementId}`, {
      params: agencyParams(agencyId),
    });
  },

  listGroupAudit: async (
    agencyId: string | null,
    groupId: string,
    params: GcPageParams,
    signal?: AbortSignal,
  ): Promise<GcPage<GcAuditEvent>> => {
    const { data } = await apiClient.get<PageEnvelope<RawAuditEvent>>(
      `${ROOT}/groups/${groupId}/audit`,
      { params: agencyParams(agencyId, toOffsetParams(params)), signal },
    );
    const page = asPage(data, params);
    return { ...page, items: page.items.map((event) => ({
      id: event.id,
      action: event.action,
      summary: event.action.replaceAll("_", " ").replaceAll(".", " / "),
      actor_name: event.actor_email,
      created_at: event.created_at,
    })) };
  },
};

export const GC_APP_DEFAULT_PAGE_SIZE = PAGE_SIZE;
