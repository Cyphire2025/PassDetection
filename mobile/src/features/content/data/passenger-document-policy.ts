import type { DocumentMetadata } from '../api/content-contracts';

export type PassengerDocumentSlotId = 'passport' | 'visa' | 'flight_ticket';

export type PassengerDocumentSlot = {
  id: PassengerDocumentSlotId;
  title: string;
  pendingMessage: string;
  documents: DocumentMetadata[];
};

const SLOT_DEFINITIONS: readonly Omit<PassengerDocumentSlot, 'documents'>[] = [
  {
    id: 'passport',
    title: 'Passport',
    pendingMessage: 'Passport images are not yet available.',
  },
  {
    id: 'visa',
    title: 'Visa',
    pendingMessage: 'Visa not yet received.',
  },
  {
    id: 'flight_ticket',
    title: 'Flight tickets',
    pendingMessage: 'Flight tickets not yet received.',
  },
];

const ITINERARY_CATEGORIES = new Set(['itinerary', 'itinerary_pdf']);

function normalizedCategory(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

export function passengerDocumentSlotId(category: string): PassengerDocumentSlotId | null {
  switch (normalizedCategory(category)) {
    case 'passport':
    case 'passport_back':
    case 'passport_front':
      return 'passport';
    case 'visa':
    case 'visa_document':
      return 'visa';
    case 'flight_ticket':
    case 'ticket':
    case 'flight_tickets':
      return 'flight_ticket';
    default:
      return null;
  }
}

export function passengerDocumentSlots(documents: DocumentMetadata[]): PassengerDocumentSlot[] {
  const bySlot = new Map<PassengerDocumentSlotId, DocumentMetadata[]>();
  for (const document of documents) {
    if (document.scope !== 'personal' || document.revoked_at) continue;
    const slotId = passengerDocumentSlotId(document.category);
    if (!slotId) continue;
    const current = bySlot.get(slotId) ?? [];
    current.push(document);
    bySlot.set(slotId, current);
  }

  return SLOT_DEFINITIONS.map((definition) => ({
    ...definition,
    documents: (bySlot.get(definition.id) ?? []).sort((left, right) => {
      if (left.category === right.category) return left.display_name.localeCompare(right.display_name);
      return left.category === 'passport' ? -1 : 1;
    }),
  }));
}

export function isItineraryDocument(category: string): boolean {
  return ITINERARY_CATEGORIES.has(normalizedCategory(category));
}

export function commonDocumentHeading(category: string): string {
  const normalized = normalizedCategory(category);
  const labels: Record<string, string> = {
    itinerary: 'Itinerary',
    itinerary_pdf: 'Itinerary',
    travel_tips: 'Travel tips',
    common_instructions: 'Common instructions',
    destination: 'Destination information',
    emergency: 'Emergency information',
    hotel: 'Hotel information',
    flight_summary: 'Flight summary',
    meeting_point: 'Meeting points',
    dress_code: 'Dress code',
    baggage: 'Baggage guidance',
    other: 'Other documents',
  };
  if (labels[normalized]) return labels[normalized];
  return normalized
    .split('_')
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(' ') || 'Documents';
}

export function shouldPrefetchPassengerDocument(document: DocumentMetadata): boolean {
  return (
    !document.revoked_at &&
    (document.scope === 'personal' || document.scope === 'common') &&
    document.metadata_state === 'ready' &&
    document.offline_available &&
    Boolean(document.size_bytes) &&
    Boolean(document.checksum_sha256)
  );
}
