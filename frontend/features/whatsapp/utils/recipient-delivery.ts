import type {
  WhatsAppRecipient,
  WhatsAppRecipientMessageStatus,
} from "../api/whatsapp.api";

const IN_PROGRESS_STATUSES = new Set(["queued", "processing"]);
const REVIEW_REQUIRED_STATUSES = new Set(["delivery_unknown"]);
const WELCOME_NO_REPEAT_STATUSES = new Set(["queued", "processing", "submitted", "sent", "delivered", "read", "delivery_unknown"]);

export type RecipientDeliveryState = Pick<WhatsAppRecipient, "message_statuses">
  & Partial<Pick<WhatsAppRecipient, "welcome_status" | "welcome_delivered" | "welcome_required_reason">>;

export function welcomeDeliveryBlockReason(recipient: RecipientDeliveryState, messageType: string): string | null {
  if (messageType === "welcome") {
    const status = getMessageStatus(recipient, "welcome");
    if (recipient.welcome_delivered || WELCOME_NO_REPEAT_STATUSES.has(recipient.welcome_status ?? status?.status ?? "") || status?.already_sent || WELCOME_NO_REPEAT_STATUSES.has(status?.latest_resend_status ?? "")) {
      return "This number has already received a welcome or its welcome delivery is still pending. Another welcome cannot be sent.";
    }
    return null;
  }
  const explicitStatusNeedsWelcome = recipient.welcome_status !== undefined
    && !["delivered", "read"].includes(recipient.welcome_status ?? "");
  if (recipient.welcome_delivered === false || explicitStatusNeedsWelcome) {
    return recipient.welcome_required_reason || "Welcome must be delivered to this number before other messages can be sent.";
  }
  return null;
}

export function canRetryOrResendRecipient(recipient: RecipientDeliveryState, messageType: string, action: "retry" | "resend") {
  if (welcomeDeliveryBlockReason(recipient, messageType)) return false;
  const status = getMessageStatus(recipient, messageType);
  if (status?.resend_blocked) return false;
  return action === "retry" ? status?.status === "failed" : Boolean(status?.already_sent);
}

export function getMessageStatus(
  recipient: Pick<WhatsAppRecipient, "message_statuses">,
  messageType: string,
): WhatsAppRecipientMessageStatus | null {
  return recipient.message_statuses?.find(
    (status) => status.message_type === messageType,
  ) ?? null;
}

export function hasAlreadySentMessage(
  recipient: Pick<WhatsAppRecipient, "message_statuses">,
  messageType: string,
): boolean {
  return getMessageStatus(recipient, messageType)?.already_sent ?? false;
}

export function isRecipientEligible(
  recipient: RecipientDeliveryState,
  messageType: string,
): boolean {
  if (welcomeDeliveryBlockReason(recipient, messageType)) return false;
  const status = getMessageStatus(recipient, messageType);
  // Each manually submitted reminder is a new broadcast. Only an active
  // delivery is excluded; the result of an earlier reminder is not a limit.
  if (messageType === "reminder") {
    return !IN_PROGRESS_STATUSES.has(status?.status ?? "")
      && !IN_PROGRESS_STATUSES.has(status?.latest_resend_status ?? "");
  }
  return (
    !status?.already_sent
    && !IN_PROGRESS_STATUSES.has(status?.status ?? "")
    && !REVIEW_REQUIRED_STATUSES.has(status?.status ?? "")
  );
}

export function countEligibleRecipients(
  recipients: Array<RecipientDeliveryState>,
  messageType: string,
): number {
  return recipients.filter(
    (recipient) => isRecipientEligible(recipient, messageType),
  ).length;
}
