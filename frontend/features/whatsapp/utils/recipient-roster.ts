import type {
  WhatsAppRecipient,
  WhatsAppRecipientRosterItem,
} from "../api/whatsapp.api";
import { getMessageStatus, isRecipientEligible, welcomeDeliveryBlockReason } from "./recipient-delivery";

export type WhatsAppRecipientRosterTab =
  | "all"
  | "sent"
  | "failed"
  | "ready"
  | "not_sent"
  | "in_progress"
  | "needs_review"
  | "shared"
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

function rosterItemMatchesFilter(
  item: WhatsAppRecipientRosterItem,
  tab: WhatsAppRecipientRosterTab,
  messageType: string | undefined,
  sharedPhones: ReadonlySet<string>,
): boolean {
  if (tab === "all") return item.kind === "recipient" || (!messageType && item.kind === "rejected");
  if (tab === "rejected") return item.kind === "rejected";
  if (tab === "replaced") return item.kind === "replaced";
  if (tab === "unidentified") return item.kind === "unidentified";
  if (item.kind !== "recipient") return false;
  if (messageType) {
    const recipient = item.recipient;
    const status = getMessageStatus(recipient, messageType);
    const statuses = [status?.status, status?.latest_resend_status];
    if (tab === "sent") return Boolean(status?.already_sent || statuses.some((value) => ["submitted", "sent", "delivered", "read"].includes(value ?? "")));
    if (tab === "failed") return statuses.includes("failed") && (messageType !== "group_invite" || !(status?.already_sent || statuses.some((value) => ["submitted", "sent", "delivered", "read"].includes(value ?? ""))));
    if (tab === "in_progress") return statuses.some((value) => value === "queued" || value === "processing");
    if (tab === "not_sent") return !status || statuses.every((value) => !value || value === "not_sent");
    if (tab === "ready") return !status?.resend_blocked && !statuses.some((value) => ["queued", "processing", "delivery_unknown"].includes(value ?? "")) && isRecipientEligible(recipient, messageType);
    if (tab === "needs_review") return statuses.includes("delivery_unknown") || Boolean(!status?.already_sent && welcomeDeliveryBlockReason(recipient, messageType));
    if (tab === "shared") return sharedPhones.has(recipient.normalized_phone_number);
  }
  return tab === "sent" ? recipientHasSentMessage(item.recipient) : recipientHasFailedMessage(item.recipient);
}

export function countRecipientRosterItems(
  items: WhatsAppRecipientRosterItem[],
  tab: WhatsAppRecipientRosterTab,
  messageType?: string,
  sharedPhones: ReadonlySet<string> = new Set(),
): number {
  let count = 0;
  for (const item of items) {
    if (rosterItemMatchesFilter(item, tab, messageType, sharedPhones)) count++;
  }
  return count;
}

export function filterRecipientRosterItems(
  items: WhatsAppRecipientRosterItem[],
  tab: WhatsAppRecipientRosterTab,
  messageType?: string,
  sharedPhones: ReadonlySet<string> = new Set(),
): WhatsAppRecipientRosterItem[] {
  return items
    .map((item, originalIndex) => ({ item, originalIndex }))
    .filter(({ item }) => rosterItemMatchesFilter(item, tab, messageType, sharedPhones))
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
      ...(item.recipient.merged_contacts ?? []).flatMap((contact) => [contact.name, ...importedValues(contact.imported_fields)]),
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

type SearchValue = { text: string; digits: string };
export type RecipientRosterSearchIndex = ReadonlyMap<WhatsAppRecipientRosterItem, readonly SearchValue[]>;

function indexedSearchValues(item: WhatsAppRecipientRosterItem, sourceNamesByPhone?: ReadonlyMap<string, string[]>): SearchValue[] {
  const values = [
    ...recipientRosterSearchValues(item),
    ...(item.kind === "recipient" ? sourceNamesByPhone?.get(item.recipient.normalized_phone_number) ?? [] : []),
  ];
  return values.flatMap((value) => value == null ? [] : [{ text: value.toLocaleLowerCase(), digits: value.replace(/\D/g, "") }]);
}

/** Build once per displayed roster, keeping imported-field work out of typing. */
export function createRecipientRosterSearchIndex(
  items: WhatsAppRecipientRosterItem[],
  sourceNamesByPhone?: ReadonlyMap<string, string[]>,
): RecipientRosterSearchIndex {
  return new Map(items.map((item) => [item, indexedSearchValues(item, sourceNamesByPhone)]));
}

export function searchRecipientRosterItems(
  items: WhatsAppRecipientRosterItem[],
  query: string,
  sourceNamesByPhone?: ReadonlyMap<string, string[]>,
  searchIndex?: RecipientRosterSearchIndex,
): WhatsAppRecipientRosterItem[] {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return items;
  const digits = normalized.replace(/\D/g, "");
  const isPhoneSearch = digits.length >= 3 && /^[+\d\s().-]+$/.test(normalized);
  return items.filter((item) =>
    (searchIndex?.get(item) ?? indexedSearchValues(item, sourceNamesByPhone)).some((value) =>
      value.text.includes(normalized) || (isPhoneSearch && value.digits.includes(digits)),
    ),
  );
}
