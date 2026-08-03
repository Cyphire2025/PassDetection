export const ROSTER_WRITE_BATCH_SIZE = 75;

/**
 * Keep each multi-row UPSERT comfortably below SQLite's conservative
 * 999-variable boundary. The roster projection binds ten values per row, so
 * 75 rows use 750 bindings and leave room for future bounded additions.
 */
export function rosterWriteBatches<T>(items: readonly T[]): readonly (readonly T[])[] {
  const batches: T[][] = [];
  for (let offset = 0; offset < items.length; offset += ROSTER_WRITE_BATCH_SIZE) {
    batches.push(items.slice(offset, offset + ROSTER_WRITE_BATCH_SIZE));
  }
  return batches;
}
