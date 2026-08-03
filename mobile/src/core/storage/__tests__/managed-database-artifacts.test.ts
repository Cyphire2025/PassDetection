import {
  isManagedDatabaseArtifactName,
  isManagedDatabaseMainName,
  managedDatabaseMainNameForArtifact,
} from '../managed-database-artifacts';

const hash = '0123456789abcdef0123456789abcdef';

test.each([
  [`gc_${hash}.db`, `gc_${hash}.db`],
  [`gc_${hash}.db-wal`, `gc_${hash}.db`],
  [`gc_${hash}.db-shm`, `gc_${hash}.db`],
  [`gc_${hash}.db-journal`, `gc_${hash}.db`],
])('recognizes only exact managed SQLite artifacts: %s', (name, mainName) => {
  expect(isManagedDatabaseArtifactName(name)).toBe(true);
  expect(managedDatabaseMainNameForArtifact(name)).toBe(mainName);
});

test.each([
  'user.db',
  `gc_${hash}.db.backup`,
  `gc_${hash}.db-wal/../user.db`,
  `../gc_${hash}.db`,
  `gc_${'a'.repeat(31)}.db`,
  `gc_${'a'.repeat(33)}.db`,
  `other_${hash}.db`,
])('preserves unrelated or malformed SQLite entries: %s', (name) => {
  expect(isManagedDatabaseArtifactName(name)).toBe(false);
  expect(managedDatabaseMainNameForArtifact(name)).toBeNull();
});

test('distinguishes main databases from their sidecars', () => {
  expect(isManagedDatabaseMainName(`gc_${hash}.db`)).toBe(true);
  expect(isManagedDatabaseMainName(`gc_${hash}.db-wal`)).toBe(false);
});
