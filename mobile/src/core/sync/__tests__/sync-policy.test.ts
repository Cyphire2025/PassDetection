import {
  assertCursorAdvance,
  hasActualSyncChanges,
  requiresBaselineSync,
  resourceVersionChanges,
  safeSyncFailureCode,
  tripIdFromMobilePath,
  UNAPPLIED_RESOURCE_VERSION,
} from '../sync-policy';

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

test('an unapplied marker forces every resource type to reconcile even at server version zero', () => {
  const previous = {
    itinerary: UNAPPLIED_RESOURCE_VERSION,
    commonDocuments: UNAPPLIED_RESOURCE_VERSION,
    personalDocuments: UNAPPLIED_RESOURCE_VERSION,
    announcements: UNAPPLIED_RESOURCE_VERSION,
    readiness: UNAPPLIED_RESOURCE_VERSION,
    roster: UNAPPLIED_RESOURCE_VERSION,
    rooming: UNAPPLIED_RESOURCE_VERSION,
    meals: UNAPPLIED_RESOURCE_VERSION,
    qr: UNAPPLIED_RESOURCE_VERSION,
  };
  expect(resourceVersionChanges(previous, {
    itinerary: 0,
    commonDocuments: 0,
    personalDocuments: 0,
    announcements: 0,
    readiness: 0,
    roster: 0,
    rooming: 0,
    meals: 0,
    qr: 0,
  })).toEqual({
    itinerary: true,
    commonDocuments: true,
    personalDocuments: true,
    announcements: true,
    readiness: true,
    roster: true,
    rooming: true,
    meals: true,
    qr: true,
  });
});

test('reports actual sync changes only for a baseline, cursor event, or version advance', () => {
  expect(hasActualSyncChanges({
    baseline: false,
    changeCount: 0,
    resourceChanges: { itinerary: false, documents: false },
  })).toBe(false);
  expect(hasActualSyncChanges({ baseline: true, changeCount: 0, resourceChanges: {} })).toBe(true);
  expect(hasActualSyncChanges({ baseline: false, changeCount: 1, resourceChanges: {} })).toBe(true);
  expect(hasActualSyncChanges({
    baseline: false,
    changeCount: 0,
    resourceChanges: { documents: true },
  })).toBe(true);
});

test('a stored zero cursor is not mistaken for a first synchronization', () => {
  expect(requiresBaselineSync({
    hasTrip: true,
    hasCursor: true,
    cursorAheadOfServer: false,
  })).toBe(false);
  expect(requiresBaselineSync({
    hasTrip: true,
    hasCursor: false,
    cursorAheadOfServer: false,
  })).toBe(true);
  expect(requiresBaselineSync({
    hasTrip: true,
    hasCursor: true,
    cursorAheadOfServer: true,
  })).toBe(true);
});

test('records only bounded non-PII synchronization failure codes', () => {
  expect(safeSyncFailureCode({ code: 'NETWORK_TIMEOUT' })).toBe('NETWORK_TIMEOUT');
  expect(safeSyncFailureCode({ code: 'contains-sensitive-text' })).toBe('SYNC_FAILED');
  expect(safeSyncFailureCode(new Error('passenger name and document URL'))).toBe('SYNC_FAILED');
  expect(safeSyncFailureCode(Object.assign(new Error('cancelled'), { name: 'AbortError' }))).toBe('SYNC_ABORTED');
});
