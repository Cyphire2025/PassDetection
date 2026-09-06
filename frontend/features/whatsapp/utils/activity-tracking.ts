import { ROUTES } from "@/constants/routes";
import { DOCUMENT_DISTRIBUTION_LANES } from "@/features/documents/config/document-distribution-lanes";
import type {
  WhatsAppActivityKind,
  WhatsAppActivitySummary,
} from "../api/whatsapp-activity.api";
import type { WhatsAppMessageType } from "../api/whatsapp.api";

export const WHATSAPP_ACTIVITY_STORAGE_KEY =
  "passdetection:whatsapp:tracked-activities:v1";
export const LEGACY_WHATSAPP_BATCH_STORAGE_KEY =
  "passdetection:whatsapp:last-batch";
export const WHATSAPP_ACTIVITY_POSITION_KEY =
  "passdetection:whatsapp:activity-position:v1";

export interface TrackedWhatsAppActivity {
  id: string;
  kind: WhatsAppActivityKind;
  startedAt: number;
  title: string;
  contextLabel: string;
  sourceGroupId: string;
  documentType: string | null;
  messageType?: WhatsAppMessageType;
  total: number;
  queued: number;
  sent: number;
  failed: number;
  deliveryUnknown: number;
  skippedAlreadySent?: number;
  skippedInProgress?: number;
  skippedDeliveryUnknown?: number;
}

export interface DisplayedWhatsAppActivity extends WhatsAppActivitySummary {
  messageType?: WhatsAppMessageType;
  startedAt?: number;
  skipped_already_sent: number;
  skipped_in_progress: number;
  skipped_delivery_unknown: number;
  refresh_error: boolean;
}

export function whatsappActivityKey(
  activity: Pick<TrackedWhatsAppActivity, "kind" | "id">,
): string {
  return `${activity.kind}:${activity.id}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isActivityKind(value: unknown): value is WhatsAppActivityKind {
  return value === "broadcast" || value === "document" || value === "qr";
}

function finiteNonNegative(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : fallback;
}

export function parseTrackedWhatsAppActivities(
  raw: string | null,
): TrackedWhatsAppActivity[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const activities: TrackedWhatsAppActivity[] = [];
    for (const candidate of parsed) {
      if (
        !isRecord(candidate)
        || typeof candidate.id !== "string"
        || !candidate.id
        || !isActivityKind(candidate.kind)
        || typeof candidate.startedAt !== "number"
        || !Number.isFinite(candidate.startedAt)
        || typeof candidate.title !== "string"
        || typeof candidate.contextLabel !== "string"
        || typeof candidate.sourceGroupId !== "string"
      ) {
        continue;
      }
      activities.push({
        id: candidate.id,
        kind: candidate.kind,
        startedAt: candidate.startedAt,
        title: candidate.title,
        contextLabel: candidate.contextLabel,
        sourceGroupId: candidate.sourceGroupId,
        documentType:
          typeof candidate.documentType === "string"
            ? candidate.documentType
            : null,
        messageType:
          candidate.messageType === "welcome"
          || candidate.messageType === "passport_link"
          || candidate.messageType === "reminder"
            ? candidate.messageType
            : undefined,
        total: finiteNonNegative(candidate.total),
        queued: finiteNonNegative(candidate.queued),
        sent: finiteNonNegative(candidate.sent),
        failed: finiteNonNegative(candidate.failed),
        deliveryUnknown: finiteNonNegative(candidate.deliveryUnknown),
        skippedAlreadySent: finiteNonNegative(candidate.skippedAlreadySent),
        skippedInProgress: finiteNonNegative(candidate.skippedInProgress),
        skippedDeliveryUnknown: finiteNonNegative(
          candidate.skippedDeliveryUnknown,
        ),
      });
    }
    return activities;
  } catch {
    return [];
  }
}

export function parseLegacyWhatsAppBatch(
  raw: string | null,
): TrackedWhatsAppActivity | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      !isRecord(parsed)
      || typeof parsed.id !== "string"
      || !parsed.id
    ) {
      return null;
    }
    return {
      id: parsed.id,
      kind: "broadcast",
      startedAt: finiteNonNegative(parsed.startedAt, Date.now()),
      title: "WhatsApp message broadcast",
      contextLabel: "Current recipient list",
      sourceGroupId:
        typeof parsed.groupId === "string" ? parsed.groupId : "unknown",
      documentType: null,
      total: 1,
      queued: 1,
      sent: 0,
      failed: 0,
      deliveryUnknown: 0,
      skippedAlreadySent: finiteNonNegative(parsed.skipped_already_sent),
      skippedInProgress: finiteNonNegative(parsed.skipped_in_progress),
      skippedDeliveryUnknown: finiteNonNegative(
        parsed.skipped_delivery_unknown,
      ),
    };
  } catch {
    return null;
  }
}

export function initialWhatsAppActivitySummary(
  activity: TrackedWhatsAppActivity,
): WhatsAppActivitySummary {
  const timestamp = new Date(activity.startedAt).toISOString();
  return {
    activity_id: activity.id,
    kind: activity.kind,
    title: activity.title,
    context_label: activity.contextLabel,
    source_group_id: activity.sourceGroupId,
    document_type: activity.documentType,
    total: activity.total,
    queued: activity.queued,
    sent: activity.sent,
    failed: activity.failed,
    delivery_unknown: activity.deliveryUnknown,
    started_at: timestamp,
    updated_at: timestamp,
  };
}

export function isWhatsAppBroadcastSourcePath(pathname: string): boolean {
  if (pathname === ROUTES.dashboard.whatsapp) return true;

  const visaPrefix = `${ROUTES.dashboard.documentDistributionVisa}/`;
  if (
    pathname.startsWith(visaPrefix)
    && pathname.slice(visaPrefix.length).split("/").filter(Boolean).length === 1
  ) {
    return true;
  }

  const flightPrefix = `${ROUTES.dashboard.documentDistributionFlightTickets}/`;
  if (pathname.startsWith(flightPrefix)) {
    const segments = pathname.slice(flightPrefix.length).split("/").filter(Boolean);
    if (
      segments.length === 3
      && (segments[1] === "international" || segments[1] === "domestic")
      && (segments[2] === "onward" || segments[2] === "return")
    ) {
      return true;
    }
  }

  const tourPrefix = `${ROUTES.dashboard.tourOperations}/groups/`;
  return pathname.startsWith(tourPrefix) && pathname.endsWith("/qr-codes");
}

export function whatsappActivitySourceHref(
  activity: Pick<
    WhatsAppActivitySummary,
    "kind" | "source_group_id" | "document_type"
  >,
): string {
  if (activity.kind === "broadcast") return ROUTES.dashboard.whatsapp;
  if (activity.kind === "qr") {
    return ROUTES.dashboard.tourOperationsGroupQrCodes(
      activity.source_group_id,
    );
  }

  const lane = Object.values(DOCUMENT_DISTRIBUTION_LANES).find(
    (candidate) => candidate.documentType === activity.document_type,
  );
  if (!lane || lane.category === "visa") {
    return ROUTES.dashboard.documentDistributionVisaGroup(
      activity.source_group_id,
    );
  }
  return ROUTES.dashboard.documentDistributionFlightLane(
    activity.source_group_id,
    lane.scope ?? "international",
    lane.leg ?? "onward",
  );
}
