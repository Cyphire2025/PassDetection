import apiClient from "@/lib/api/client";
import type { GcAuditEvent, GcPage, GcPageParams } from "../types";
import type { PageEnvelope, RawAuditEvent } from "./gc-app-wire.types";
import { ROOT, asPage, toOffsetParams, agencyParams } from "./gc-app-transport";

export const gcAppAuditApi = {
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
    return { ...page, items: page.items.map(normalizeAuditEvent) };
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
    return { ...page, items: page.items.map(normalizeAuditEvent) };
  },
};

function normalizeAuditEvent(event: RawAuditEvent): GcAuditEvent {
  return {
    id: event.id,
    action: event.action,
    summary: event.action.replaceAll("_", " ").replaceAll(".", " / "),
    actor_name: event.actor_email,
    created_at: event.created_at,
  };
}
