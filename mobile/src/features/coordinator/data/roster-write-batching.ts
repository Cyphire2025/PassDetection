import {
  sqliteBindBatches,
  sqliteRowsPerBatch,
} from '@/core/storage/sqlite-batching';

const ROSTER_BINDINGS_PER_ROW = 19;

export const ROSTER_WRITE_BATCH_SIZE = sqliteRowsPerBatch(ROSTER_BINDINGS_PER_ROW);

/**
 * Keep each multi-row UPSERT comfortably below SQLite's conservative
 * 999-variable boundary. The largest owned roster statement binds nineteen
 * values per row, so 47 rows use 893 bindings and leave a safety margin.
 */
export function rosterWriteBatches<T>(items: readonly T[]): readonly (readonly T[])[] {
  return sqliteBindBatches(items, ROSTER_BINDINGS_PER_ROW);
}
