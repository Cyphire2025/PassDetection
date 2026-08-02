import { assertCursorAdvance, resourceVersionChanges, tripIdFromMobilePath } from '../sync-policy';

const tripId = '33333333-3333-4333-8333-333333333333';

test('requires monotonic cursors and progress while more pages remain', () => {
  expect(() => assertCursorAdvance(4, 5, true)).not.toThrow();
  expect(() => assertCursorAdvance(5, 5, false)).not.toThrow();
  expect(() => assertCursorAdvance(5, 4, false)).toThrow('backwards');
  expect(() => assertCursorAdvance(5, 5, true)).toThrow('did not advance');
});

test('extracts only trip-scoped mobile paths for immediate purge', () => {
  expect(tripIdFromMobilePath(`/mobile/trips/${tripId}/manifest`)).toBe(tripId);
  expect(tripIdFromMobilePath(`/mobile/coordinator/groups/${tripId}/passengers`)).toBe(tripId);
  expect(tripIdFromMobilePath('/mobile/trips/../../other')).toBeNull();
  expect(tripIdFromMobilePath(`/admin/groups/${tripId}`)).toBeNull();
});

test('resource fingerprints trigger a room refresh without a journal event', () => {
  const previous = {
    itinerary: 4,
    commonDocuments: 2,
    personalDocuments: 8,
    announcements: 5,
    readiness: 7,
    roster: 11,
    rooming: 402,
    meals: 3,
    qr: 9,
  };
  expect(resourceVersionChanges(previous, { ...previous, rooming: 517 })).toMatchObject({
    rooming: true,
    meals: false,
    qr: false,
  });
});
