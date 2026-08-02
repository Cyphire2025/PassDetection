const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}';
const TRIP_PATH = new RegExp(`^/mobile/(?:trips|manager/groups|coordinator/groups)/(${UUID})(?:/|\\?|$)`, 'i');

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
