import type {
  WhatsAppRecipient,
  WhatsAppRecipientRosterItem,
} from "../api/whatsapp.api";

export type WhatsAppRecipientRosterTab =
  | "all"
  | "sent"
  | "failed"
  | "rejected"
  | "replaced"
  | "unidentified";

export function recipientHasSentMessage(
  recipient: Pick<WhatsAppRecipient, "message_statuses">,
): boolean {
  return recipient.message_statuses.some((status) => status.already_sent);
}

export function recipientHasFailedMessage(
  recipient: Pick<WhatsAppRecipient, "message_statuses">,
): boolean {
  return recipient.message_statuses.some(
    (status) =>
      status.status === "failed"
      || status.latest_resend_status === "failed",
  );
}

export function filterRecipientRosterItems(
  items: WhatsAppRecipientRosterItem[],
  tab: WhatsAppRecipientRosterTab,
): WhatsAppRecipientRosterItem[] {
  return items
    .map((item, originalIndex) => ({ item, originalIndex }))
    .filter(({ item }) => {
      if (tab === "all") {
        return item.kind === "recipient" || item.kind === "rejected";
      }
      if (tab === "rejected") return item.kind === "rejected";
      if (tab === "replaced") return item.kind === "replaced";
      if (tab === "unidentified") return item.kind === "unidentified";
      if (item.kind !== "recipient") return false;
      return tab === "sent"
        ? recipientHasSentMessage(item.recipient)
        : recipientHasFailedMessage(item.recipient);
    })
    .sort(
      (left, right) =>
        left.item.display_order - right.item.display_order
        || left.originalIndex - right.originalIndex,
    )
    .map(({ item }) => item);
}
