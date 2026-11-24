import type { WhatsAppRecipient } from "../api/whatsapp.api";
import type { WhatsAppBroadcastSourceContacts } from "../api/whatsapp-source-groups.api";
import { getMessageStatus } from "../utils/recipient-delivery";

export interface RecipientPerson {
  key: string;
  recipient: WhatsAppRecipient;
  name: string;
  fields: Record<string, string>;
  mergedId: string | null;
}
export function recipientPeople(
  recipients: WhatsAppRecipient[],
  contacts: WhatsAppBroadcastSourceContacts["contacts"] = [],
): RecipientPerson[] {
  const byRecipient = new Map<
    string,
    WhatsAppBroadcastSourceContacts["contacts"]
  >();
  for (const contact of contacts) {
    if (!contact.recipient_id) continue;
    const entries = byRecipient.get(contact.recipient_id) ?? [];
    entries.push(contact);
    byRecipient.set(contact.recipient_id, entries);
  }
  return recipients.flatMap((recipient) => {
    const sourcePeople = byRecipient.get(recipient.id) ?? [];
    if (sourcePeople.length)
      return sourcePeople.map((contact) => ({
        key: `${recipient.id}:source:${contact.source_submission_id}`,
        recipient: { ...recipient, is_source_managed: true },
        name: contact.name || "Unnamed recipient",
        fields: contact.imported_fields,
        mergedId: null,
      }));
    return [
      {
        key: recipient.id,
        recipient,
        name: recipient.name || "Unnamed recipient",
        fields: recipient.imported_fields,
        mergedId: null,
      },
      ...(recipient.merged_contacts ?? []).map((contact) => ({
        key: `${recipient.id}:${contact.id}`,
        recipient,
        name: contact.name || "Unnamed recipient",
        fields: contact.imported_fields,
        mergedId: contact.id,
      })),
    ];
  });
}
export function detailLabel(key: string) {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function welcomeStatus(person: RecipientPerson) {
  const saved = getMessageStatus(person.recipient, "welcome");
  return (
    saved?.latest_resend_status ??
    saved?.status ??
    person.recipient.welcome_status ??
    "not_sent"
  );
}

export function recipientWelcomeSummary(people: RecipientPerson[]) {
  const statuses = new Map<RecipientPerson, string>();
  let failedCount = 0;
  let notSentCount = 0;
  for (const person of people) {
    const status = welcomeStatus(person);
    statuses.set(person, status);
    if (status === "failed") failedCount += 1;
    if (status === "not_sent") notSentCount += 1;
  }
  return { statuses, failedCount, notSentCount };
}

export function openRecipientDetails(people: RecipientPerson[], keys: string[]) {
  const byKey = new Map<string, RecipientPerson>();
  for (const person of people) {
    if (!byKey.has(person.key)) byKey.set(person.key, person);
  }
  return keys.flatMap((key) => {
    const person = byKey.get(key);
    return person ? [person] : [];
  });
}
