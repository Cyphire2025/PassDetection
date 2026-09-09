import type {
  WhatsAppRecipient,
  WhatsAppRecipientMessageStatus,
} from "../api/whatsapp.api";

const IN_PROGRESS_STATUSES = new Set(["queued", "processing"]);
const REVIEW_REQUIRED_STATUSES = new Set(["delivery_unknown"]);

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
  recipient: Pick<WhatsAppRecipient, "message_statuses">,
  messageType: string,
): boolean {
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
  recipients: Array<Pick<WhatsAppRecipient, "message_statuses">>,
  messageType: string,
): number {
  return recipients.filter(
    (recipient) => isRecipientEligible(recipient, messageType),
  ).length;
}
