import type { ClientManagerAccount, GcAppControlPatch, GcAppGroupControl, GcGroupReference } from "../types";
import type { RawClientManager, RawGroup, RawGroupAccess } from "./gc-app-wire.types";

export function normalizeGroup(group: RawGroup): GcGroupReference {
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
    gc_removed_at: group.access?.removed_at ?? null,
  };
}

export function normalizeClientManager(manager: RawClientManager): ClientManagerAccount {
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

export function normalizeControl(access: RawGroupAccess, group?: RawGroup): GcAppGroupControl {
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
    gc_removed_at: access.removed_at ?? null,
    revision: access.revision,
    organization_id: organizationId,
    active_mobile_users: access.active_mobile_users ?? 0,
    synced_device_count: access.synced_device_count ?? 0,
    last_successful_sync_at: access.last_successful_sync_at,
    app_availability: access.app_availability ?? "unavailable",
    app_availability_reason: access.app_availability_reason ?? null,
    app_availability_evaluated_at: access.app_availability_evaluated_at,
    versions: {
      itinerary_version: access.itinerary_version,
      common_document_version: access.common_document_version,
      announcement_version: access.announcement_version,
    },
  };
}

export function fullControlBody(control: GcAppGroupControl, patch: GcAppControlPatch, enabled = control.gc_app_enabled) {
  if (!control.organization_id) {
    throw new Error("The GC App group is missing its client organization. Refresh before changing access.");
  }
  return {
    client_organization_id: control.organization_id,
    enabled: patch.enabled ?? enabled,
    passenger_access_enabled: patch.passenger_access_enabled ?? control.passenger_access_enabled,
    client_manager_access_enabled: patch.client_manager_access_enabled ?? control.client_manager_access_enabled,
    coordinator_access_enabled: patch.coordinator_access_enabled ?? control.coordinator_access_enabled,
    access_starts_at: patch.access_starts_at === undefined ? control.access_starts_at : patch.access_starts_at,
    access_expires_at: patch.access_expires_at === undefined ? control.access_expires_at : patch.access_expires_at,
    expected_revision: control.revision,
  };
}
