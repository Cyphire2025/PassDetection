const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}';
const TRIP_PATH = new RegExp(`^/mobile/(?:trips|manager/groups|coordinator/groups)/(${UUID})(?:/|\\?|$)`, 'i');

// Stored resource versions are applied-state markers. A negative value is never
// emitted by the server and means that this device must reconcile the resource
// before it may advance its durable sync cursor.
export const UNAPPLIED_RESOURCE_VERSION = -1;

export function tripIdFromMobilePath(path: string): string | null {
  return TRIP_PATH.exec(path)?.[1] ?? null;
}

export function assertCursorAdvance(current: number, next: number, hasMore: boolean): void {
  if (!Number.isSafeInteger(current) || !Number.isSafeInteger(next) || next < current) {
    throw new Error('The synchronization cursor moved backwards.');
  }
  if (hasMore && next === current) throw new Error('The synchronization cursor did not advance.');
}

export type StoredResourceVersions = {
  itinerary: number;
  commonDocuments: number;
  personalDocuments: number;
  announcements: number;
  readiness: number;
  roster: number;
  rooming: number;
  meals: number;
  qr: number;
};

export function resourceVersionChanges(
  previous: StoredResourceVersions | null,
  next: StoredResourceVersions,
): Record<keyof StoredResourceVersions, boolean> {
  return {
    itinerary: previous?.itinerary !== next.itinerary,
    commonDocuments: previous?.commonDocuments !== next.commonDocuments,
    personalDocuments: previous?.personalDocuments !== next.personalDocuments,
    announcements: previous?.announcements !== next.announcements,
    readiness: previous?.readiness !== next.readiness,
    roster: previous?.roster !== next.roster,
    rooming: previous?.rooming !== next.rooming,
    meals: previous?.meals !== next.meals,
    qr: previous?.qr !== next.qr,
  };
}

export function hasActualSyncChanges(input: {
  baseline: boolean;
  changeCount: number;
  resourceChanges: Record<string, boolean>;
}): boolean {
  return input.baseline
    || input.changeCount > 0
    || Object.values(input.resourceChanges).some(Boolean);
}

export function requiresBaselineSync(input: {
  hasTrip: boolean;
  hasCursor: boolean;
  cursorAheadOfServer: boolean;
}): boolean {
  return !input.hasTrip || !input.hasCursor || input.cursorAheadOfServer;
}

export function safeSyncFailureCode(error: unknown): string {
  if (
    typeof error === 'object' &&
    error !== null &&
    'code' in error &&
    typeof error.code === 'string' &&
    /^[A-Z][A-Z0-9_]{0,63}$/.test(error.code)
  ) {
    return error.code;
  }
  if (error instanceof Error && error.name === 'AbortError') return 'SYNC_ABORTED';
  return 'SYNC_FAILED';
}

export type SyncFailureCategory =
  | 'authentication'
  | 'authorization'
  | 'rate_limited'
  | 'network'
  | 'server'
  | 'storage'
  | 'integrity'
  | 'cancelled'
  | 'unknown';

export type SafeSyncFailure = Readonly<{
  category: SyncFailureCategory;
  retryable: boolean;
  code: string;
}>;

/** Returns a bounded diagnostic without serializing an exception message or PII. */
export function classifySyncFailure(error: unknown): SafeSyncFailure {
  const status = typeof error === 'object' && error !== null && 'status' in error
    && typeof error.status === 'number'
    ? error.status
    : null;
  const code = safeSyncFailureCode(error);
  const name = error instanceof Error ? error.name : '';

  if (name === 'AbortError' || code === 'SYNC_CONTEXT_CHANGED') {
    return { category: 'cancelled', retryable: true, code: 'SYNC_CANCELLED' };
  }
  if (status === 401) return { category: 'authentication', retryable: false, code: 'SYNC_AUTHENTICATION' };
  if (status === 403) return { category: 'authorization', retryable: false, code: 'SYNC_AUTHORIZATION' };
  if (status === 429) return { category: 'rate_limited', retryable: true, code: 'SYNC_RATE_LIMITED' };
  if (status !== null && status >= 500) return { category: 'server', retryable: true, code: 'SYNC_SERVER' };
  if (code.includes('INTEGRITY') || code.includes('CHECKSUM')) {
    return { category: 'integrity', retryable: false, code: 'SYNC_INTEGRITY' };
  }
  if (code.includes('DATABASE') || code.includes('STORAGE') || code.includes('VAULT')) {
    return { category: 'storage', retryable: true, code: 'SYNC_STORAGE' };
  }
  if (error instanceof TypeError || name === 'TimeoutError') {
    return { category: 'network', retryable: true, code: 'SYNC_NETWORK' };
  }
  return { category: 'unknown', retryable: true, code: 'SYNC_UNKNOWN' };
}
