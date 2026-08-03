import {
  ROSTER_WRITE_BATCH_SIZE,
  rosterWriteBatches,
} from '../roster-write-batching';

test('bounds a 1,500-passenger roster to twenty SQLite write batches', () => {
  const passengers = Array.from({ length: 1_500 }, (_, index) => ({ id: `passenger-${index}` }));
  const batches = rosterWriteBatches(passengers);

  expect(ROSTER_WRITE_BATCH_SIZE).toBe(75);
  expect(batches).toHaveLength(20);
  expect(batches.every((batch) => batch.length <= ROSTER_WRITE_BATCH_SIZE)).toBe(true);
  expect(batches.flat()).toEqual(passengers);
});

test('does not create an empty statement batch', () => {
  expect(rosterWriteBatches([])).toEqual([]);
});
