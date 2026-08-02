import type { DocumentMetadata } from '../../api/content-contracts';
import {
  commonDocumentHeading,
  isItineraryDocument,
  passengerDocumentSlots,
  shouldPrefetchPassengerDocument,
} from '../passenger-document-policy';

const base: DocumentMetadata = {
  id: '11111111-1111-4111-8111-111111111111',
  trip_id: '22222222-2222-4222-8222-222222222222',
  passenger_id: '33333333-3333-4333-8333-333333333333',
  scope: 'personal',
  category: 'passport',
  display_name: 'Passport',
  content_type: 'image/jpeg',
  size_bytes: 1024,
  version: 1,
  checksum_sha256: 'a'.repeat(64),
  offline_available: true,
  metadata_state: 'ready',
  updated_at: '2026-08-02T10:00:00.000Z',
  revoked_at: null,
};

test('always returns the three passenger document slots in product order', () => {
  const slots = passengerDocumentSlots([
    base,
    { ...base, id: '44444444-4444-4444-8444-444444444444', category: 'passport_back', display_name: 'Passport back' },
    { ...base, id: '55555555-5555-4555-8555-555555555555', category: 'visa', display_name: 'Visa' },
  ]);

  expect(slots.map((slot) => slot.id)).toEqual(['passport', 'visa', 'flight_ticket']);
  expect(slots[0]?.documents).toHaveLength(2);
  expect(slots[1]?.documents).toHaveLength(1);
  expect(slots[2]?.pendingMessage).toBe('Flight tickets not yet received.');
});

test('recognizes the fixed itinerary category and humanizes common categories', () => {
  expect(isItineraryDocument('itinerary_pdf')).toBe(true);
  expect(commonDocumentHeading('travel_tips')).toBe('Travel tips');
  expect(commonDocumentHeading('destination_notes')).toBe('Destination Notes');
});

test('prefetches only ready authorized personal or common files', () => {
  expect(shouldPrefetchPassengerDocument(base)).toBe(true);
  expect(shouldPrefetchPassengerDocument({ ...base, metadata_state: 'pending', size_bytes: null, checksum_sha256: null, offline_available: false })).toBe(false);
  expect(shouldPrefetchPassengerDocument({ ...base, scope: 'coordinator' })).toBe(false);
  expect(shouldPrefetchPassengerDocument({ ...base, revoked_at: '2026-08-02T10:01:00.000Z' })).toBe(false);
});
