import type { WhatsAppBroadcastGroupDetail, WhatsAppRecipient } from "../api/whatsapp.api";
import type { WhatsAppBroadcastSourceContacts } from "../api/whatsapp-source-groups.api";

export function syntheticRecipient(index: number): WhatsAppRecipient {
  return {
    id: `recipient-${index}`,
    name: `Traveller ${String(index).padStart(3, "0")}`,
    phone_number: `+91900000${String(index).padStart(4, "0")}`,
    normalized_phone_number: `+91900000${String(index).padStart(4, "0")}`,
    imported_fields: { department: `Team ${index}` },
    message_statuses: [],
    welcome_status: index % 2 ? "failed" : "not_sent",
  };
}

export function syntheticRecipientGroup(count: number): WhatsAppBroadcastGroupDetail {
  return {
    id: "synthetic-broadcast", name: "Synthetic broadcast", recipient_count: count,
    total_contact_count: count, recipient_opt_in_confirmed: true,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    recipients: Array.from({ length: count }, (_, index) => syntheticRecipient(index)),
    support_contacts: [], rejected_contact_count: 0,
  };
}

export function syntheticSourceContact(
  id: string,
  recipientId: string | null,
): WhatsAppBroadcastSourceContacts["contacts"][number] {
  return {
    source_submission_id: id, source_group_id: "synthetic-trip",
    source_group_name: "Synthetic trip", source_import_only: false,
    name: id, phone_number: "+919000000000", normalized_phone_number: "+919000000000",
    issue: recipientId ? null : "invalid_phone", recipient_id: recipientId,
    imported_fields: { department: "Shared source department" },
  };
}
