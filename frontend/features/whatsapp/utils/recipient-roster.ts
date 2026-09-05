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

function importedValues(fields: Record<string, unknown>): string[] {
  return Object.entries(fields).flatMap(([key, value]) => [
    key,
    typeof value === "string" || typeof value === "number"
      ? String(value)
      : JSON.stringify(value) ?? "",
  ]);
}

function recipientRosterSearchValues(
  item: WhatsAppRecipientRosterItem,
): Array<string | null | undefined> {
  if (item.kind === "recipient") {
    return [
      item.recipient.name,
      item.recipient.phone_number,
      item.recipient.normalized_phone_number,
      ...importedValues(item.recipient.imported_fields),
    ];
  }
  if (item.kind === "rejected") {
    return [
      item.rejected_contact.raw_name,
      item.rejected_contact.raw_phone_number,
      item.rejected_contact.source_file_name,
      item.rejected_contact.sheet_name,
      ...importedValues(item.rejected_contact.imported_fields ?? {}),
    ];
  }
  if (item.kind === "replaced") {
    return [
      item.replaced_recipient.name,
      item.replaced_recipient.phone_number,
      item.replaced_recipient.normalized_phone_number,
      item.replaced_recipient.replacement_name,
      item.replaced_recipient.replacement_phone,
      item.replaced_recipient.client_group_name,
      ...importedValues(item.replaced_recipient.imported_fields),
    ];
  }
  return [
    item.unidentified_upload.name,
    item.unidentified_upload.phone_number,
    item.unidentified_upload.email,
    item.unidentified_upload.client_group_name,
    ...importedValues(item.unidentified_upload.details),
  ];
}

export function searchRecipientRosterItems(
  items: WhatsAppRecipientRosterItem[],
  query: string,
): WhatsAppRecipientRosterItem[] {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return items;
  const digits = normalized.replace(/\D/g, "");
  const isPhoneSearch = digits.length >= 3 && /^[+\d\s().-]+$/.test(normalized);
  return items.filter((item) =>
    recipientRosterSearchValues(item).some((value) =>
      value?.toLocaleLowerCase().includes(normalized)
      || (isPhoneSearch && value?.replace(/\D/g, "").includes(digits)),
    ),
  );
}
