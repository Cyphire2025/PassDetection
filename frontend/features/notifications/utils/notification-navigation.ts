import { ROUTES } from "@/constants/routes";
import type { OperationalNotification } from "../types";

const SAFE_ENTITY_ID = /^[A-Za-z0-9_-]{1,128}$/;

export function notificationTargetRoute(
  notification: Pick<OperationalNotification, "entity_type" | "entity_id">,
): string | null {
  const entityType = notification.entity_type?.toLowerCase() ?? "";
  const entityId = notification.entity_id;

  if (
    entityType === "email_inbox" ||
    entityType === "email_analysis" ||
    entityType === "email_action_proposal" ||
    entityType === "email_deadline" ||
    entityType === "email_reply_draft"
  ) {
    return ROUTES.dashboard.emailIntegrationsInbox;
  }

  if (entityType === "email_review") {
    return ROUTES.dashboard.emailIntegrationsReview;
  }

  if (entityType === "email_connection") {
    return ROUTES.dashboard.emailIntegrations;
  }

  if (!entityId || !SAFE_ENTITY_ID.test(entityId)) return null;

  switch (entityType) {
    case "email_message":
      return ROUTES.dashboard.emailIntegrationMessage(entityId);
    case "passport":
    case "passenger":
      return ROUTES.dashboard.passportDetail(entityId);
    case "group":
    case "travel_group":
      return ROUTES.dashboard.passportGroup(entityId);
    case "document_group":
      return ROUTES.dashboard.documentGroup(entityId);
    case "rooming_group":
      return ROUTES.dashboard.roomingGroup(entityId);
    default:
      return null;
  }
}

export function readNotificationMetadata(
  metadata: Record<string, unknown> | null,
  key: string,
): string | null {
  const value = metadata?.[key];
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed.slice(0, 160) : null;
}
