import type { SQLiteDatabase } from 'expo-sqlite';

/**
 * Stay below SQLite's conservative 999-variable default and leave room for
 * fixed predicates or future columns without changing every caller's batch
 * sizing contract.
 */
export const SQLITE_SAFE_BIND_BUDGET = 900;

export function sqliteRowsPerBatch(
  bindingsPerRow: number,
  fixedBindings = 0,
): number {
  if (!Number.isSafeInteger(bindingsPerRow) || bindingsPerRow < 1) {
    throw new Error('SQLite row binding width must be a positive integer.');
  }
  if (!Number.isSafeInteger(fixedBindings) || fixedBindings < 0) {
    throw new Error('SQLite fixed binding count must be a non-negative integer.');
  }
  const available = SQLITE_SAFE_BIND_BUDGET - fixedBindings;
  if (available < bindingsPerRow) {
    throw new Error('One SQLite row exceeds the conservative binding budget.');
  }
  return Math.floor(available / bindingsPerRow);
}

export function sqliteBindBatches<T>(
  items: readonly T[],
  bindingsPerRow: number,
  fixedBindings = 0,
): readonly (readonly T[])[] {
  const batchSize = sqliteRowsPerBatch(bindingsPerRow, fixedBindings);
  const batches: T[][] = [];
  for (let offset = 0; offset < items.length; offset += batchSize) {
    batches.push(items.slice(offset, offset + batchSize));
  }
  return batches;
}

export function sqliteValuesClause(rowCount: number, bindingsPerRow: number): string {
  if (!Number.isSafeInteger(rowCount) || rowCount < 1) {
    throw new Error('SQLite VALUES requires at least one row.');
  }
  if (!Number.isSafeInteger(bindingsPerRow) || bindingsPerRow < 1) {
    throw new Error('SQLite VALUES row width must be a positive integer.');
  }
  const row = `(${Array.from({ length: bindingsPerRow }, () => '?').join(', ')})`;
  return Array.from({ length: rowCount }, () => row).join(', ');
}

function replacementTableName(value: string): string {
  if (!/^mobile_[a-z0-9_]+_replacement_ids$/.test(value)) {
    throw new Error('The SQLite replacement table name was invalid.');
  }
  return value;
}

/**
 * Builds an exact incoming-id set on the transaction connection. Callers then
 * delete target rows with NOT EXISTS instead of producing an unbounded NOT IN
 * statement. The temp set and target mutations participate in the caller's
 * BEGIN IMMEDIATE transaction, so a later failure cannot publish a partial
 * authoritative replacement.
 */
export async function stageSqliteReplacementIds(
  transaction: SQLiteDatabase,
  table: string,
  identifiers: readonly string[],
  assertActive?: () => void,
): Promise<void> {
  const tableName = replacementTableName(table);
  if (new Set(identifiers).size !== identifiers.length) {
    throw new Error('An authoritative SQLite replacement repeated an identifier.');
  }
  assertActive?.();
  await transaction.runAsync(
    `CREATE TEMP TABLE IF NOT EXISTS ${tableName} (id TEXT PRIMARY KEY NOT NULL) WITHOUT ROWID`,
  );
  await transaction.runAsync(`DELETE FROM ${tableName}`);
  for (const batch of sqliteBindBatches(identifiers, 1)) {
    assertActive?.();
    await transaction.runAsync(
      `INSERT INTO ${tableName} (id) VALUES ${sqliteValuesClause(batch.length, 1)}`,
      ...batch,
    );
  }
  assertActive?.();
}
