import type {
  DistributedDocument,
  DocumentPassengerReviewRow,
  DistributionDocumentType,
} from "@/types/document-distribution.types";
import type { WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";

export interface BroadcastDocumentEntry {
  row: DocumentPassengerReviewRow;
  source: NonNullable<WhatsAppBroadcastGroupDetail["linked_client_groups"]>[number];
  documents: DistributedDocument[];
}

export const documentTypes: DistributionDocumentType[] = [
  "visa", "flight_ticket", "flight_ticket_arrival",
  "flight_ticket_domestic", "flight_ticket_domestic_arrival",
];

export const filters = [
  ["all", "All"], ["multiple", "Multiple PDFs"], ["shared", "Shared PDF"],
  ["assigned", "Assigned"], ["missing", "Missing"],
  ["sent", "Sent"], ["not_sent", "Not sent"],
] as const;

const accepted = new Set(["submitted", "sent", "delivered", "read"]);

export function buildBroadcastDocumentProjection(
  allEntries: BroadcastDocumentEntry[],
  passengerLinks: {
    group_id: string;
    passenger_id: string
  }[] | undefined,
  filter: string,
  q: string,
) {
  const linkedPassengers = new Set(
    passengerLinks?.map((link) => `${link.group_id}:${link.passenger_id}`),
  );
  const entries = allEntries.filter((entry) =>
    linkedPassengers.has(`${entry.source.id}:${entry.row.passenger_id}`),
  );
  const documentIdentity = (
    entry: BroadcastDocumentEntry,
    document: DistributedDocument,
  ) => `${entry.source.id}:${document.url?.split("?")[0] ?? document.id}`;
  const sharedUrls = new Map<string, Set<string>>();
  for (const entry of allEntries) {
    for (const document of entry.documents) {
      const identity = documentIdentity(entry, document);
      const people = sharedUrls.get(identity) ?? new Set<string>();
      people.add(entry.row.passenger_id);
      sharedUrls.set(identity, people);
    }
  }
  const counts: Record<(typeof filters)[number][0], number> = {
    all: entries.length,
    multiple: 0,
    shared: 0,
    assigned: 0,
    missing: 0,
    sent: 0,
    not_sent: 0,
  };
  const displayed: BroadcastDocumentEntry[] = [];
  for (const entry of entries) {
    const assigned = entry.documents.length > 0;
    const sent = assigned && entry.documents.every(document => accepted.has(document.delivery_status));
    const multiple = (entry.row.assigned_pdf_count ?? entry.documents.length) > 1;
    const shared = entry.documents.some(document =>
      (sharedUrls.get(documentIdentity(entry, document))?.size ?? 0) > 1);
    if (multiple) counts.multiple += 1;
    if (shared) counts.shared += 1;
    if (assigned) counts.assigned += 1;
    else counts.missing += 1;
    if (sent) counts.sent += 1;
    else if (assigned) counts.not_sent += 1;
    const matches = filter === "multiple" ? multiple
      : filter === "shared" ? shared
        : filter === "assigned" ? assigned
          : filter === "missing" ? !assigned
            : filter === "sent" ? sent
              : filter === "not_sent" ? assigned && !sent : true;
    if (matches && (!q || `${entry.row.passenger_name} ${entry.row.passport_number ?? ""}`
      .toLocaleLowerCase().includes(q))) displayed.push(entry);
  }
  return { entries, displayed, counts };
}
