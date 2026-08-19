import {
  SQLITE_SAFE_BIND_BUDGET,
  sqliteBindBatches,
  sqliteRowsPerBatch,
  sqliteValuesClause,
  stageSqliteReplacementIds,
} from '../sqlite-batching';

describe('SQLite bounded write batching', () => {
  it('derives conservative batch sizes from row width and fixed predicates', () => {
    expect(sqliteRowsPerBatch(19)).toBe(47);
    expect(sqliteRowsPerBatch(15)).toBe(60);
    expect(sqliteRowsPerBatch(1, 3)).toBe(897);
    expect(sqliteBindBatches(Array.from({ length: 10_000 }, (_, id) => id), 19))
      .toHaveLength(Math.ceil(10_000 / 47));
    expect(sqliteValuesClause(2, 3)).toBe('(?, ?, ?), (?, ?, ?)');
  });

  it('stages 10k identifiers in O(batches) with no statement over the bind budget', async () => {
    const transaction = {
      runAsync: jest.fn(async (_sql: string, ..._parameters: unknown[]) => ({
        changes: 1,
        lastInsertRowId: 0,
      })),
    };
    const identifiers = Array.from({ length: 10_000 }, (_, id) => `id-${id}`);

    await stageSqliteReplacementIds(
      transaction as never,
      'mobile_test_replacement_ids',
      identifiers,
    );

    expect(transaction.runAsync).toHaveBeenCalledTimes(2 + Math.ceil(10_000 / 900));
    expect(transaction.runAsync.mock.calls.slice(2).every(
      (call) => call.slice(1).length <= SQLITE_SAFE_BIND_BUDGET,
    )).toBe(true);
  });

  it('rejects duplicate authoritative identifiers before mutating the transaction', async () => {
    const transaction = { runAsync: jest.fn() };
    await expect(stageSqliteReplacementIds(
      transaction as never,
      'mobile_test_replacement_ids',
      ['same', 'same'],
    )).rejects.toThrow('repeated an identifier');
    expect(transaction.runAsync).not.toHaveBeenCalled();
  });
});
