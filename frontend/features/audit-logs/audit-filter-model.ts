import type { AuditLogFilters, AuditLogResult } from "@/features/operations/api/operations.api";

export interface AuditFilterState {
  startAt: string;
  endAt: string;
  actor: string;
  eventType: string;
  entityType: string;
  entityId: string;
  result: "" | AuditLogResult;
  agencyId: string;
}

export const EMPTY_FILTERS: AuditFilterState = {
  startAt: "",
  endAt: "",
  actor: "",
  eventType: "",
  entityType: "",
  entityId: "",
  result: "",
  agencyId: "",
};

export function toApiFilters(filters: AuditFilterState, includeAgency: boolean): AuditLogFilters {
  const startAt = toIso(filters.startAt);
  const endAt = toIso(filters.endAt);
  const actor = normalized(filters.actor);
  const eventType = normalized(filters.eventType);
  const entityType = normalized(filters.entityType);
  const entityId = normalized(filters.entityId);
  const result = filters.result || null;
  const agencyId = normalized(filters.agencyId);
  return {
    ...(startAt ? { start_at: startAt } : {}),
    ...(endAt ? { end_at: endAt } : {}),
    ...(actor ? { actor } : {}),
    ...(eventType ? { event_type: eventType } : {}),
    ...(entityType ? { entity_type: entityType } : {}),
    ...(entityId ? { entity_id: entityId } : {}),
    ...(result ? { result } : {}),
    ...(includeAgency && agencyId ? { agency_id: agencyId } : {}),
  };
}

function toIso(value: string) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function normalized(value: string) {
  return value.trim().replace(/\s+/g, " ");
}

export function auditResultFilter(value: string): AuditFilterState["result"] {
  return value === "success"
    || value === "blocked"
    || value === "denied"
    || value === "failed"
    ? value
    : "";
}

export function formatCompactTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recorded";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function toLabel(value: string) {
  return value.replace(/[_.]/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}
