import {
  ROSTER_WRITE_BATCH_SIZE,
  rosterWriteBatches,
} from '../roster-write-batching';

test('bounds a 1,500-passenger roster below the SQLite binding ceiling', () => {
  const passengers = Array.from({ length: 1_500 }, (_, index) => ({ id: `passenger-${index}` }));
  const batches = rosterWriteBatches(passengers);

  expect(ROSTER_WRITE_BATCH_SIZE).toBe(47);
  expect(batches).toHaveLength(Math.ceil(1_500 / 47));
  expect(batches.every((batch) => batch.length <= ROSTER_WRITE_BATCH_SIZE)).toBe(true);
  expect(batches.flat()).toEqual(passengers);
});

test('does not create an empty statement batch', () => {
  expect(rosterWriteBatches([])).toEqual([]);
});

test('batches the 10,000-passenger capacity below SQLite variable limits', () => {
  const passengers = Array.from({ length: 10_000 }, (_, index) => ({ id: index }));
  const batches = rosterWriteBatches(passengers);

  expect(batches).toHaveLength(Math.ceil(10_000 / ROSTER_WRITE_BATCH_SIZE));
  expect(Math.max(...batches.map((batch) => batch.length * 19))).toBeLessThanOrEqual(900);
  expect(batches.flat()).toEqual(passengers);
});

test('keeps deterministic 10,000-row batching below the local CPU budget', () => {
  const passengers = Array.from({ length: 10_000 }, (_, index) => ({ id: index }));
  const samples = Array.from({ length: 9 }, () => {
    const startedAt = performance.now();
    const batches = rosterWriteBatches(passengers);
    expect(batches.flat()).toHaveLength(passengers.length);
    return performance.now() - startedAt;
  }).sort((left, right) => left - right);
  const medianMilliseconds = samples[Math.floor(samples.length / 2)] ?? Number.POSITIVE_INFINITY;

  // This measures only deterministic JS batching. Native SQLCipher/FTS latency
  // remains a device benchmark gate and is intentionally reported separately.
  expect(medianMilliseconds).toBeLessThan(50);
});
