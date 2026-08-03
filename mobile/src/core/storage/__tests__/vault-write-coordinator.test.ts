import {
  TripVaultPurgeInProgressError,
  TripVaultWriteCoordinator,
  VaultWriteCoordinator,
} from '../vault-write-coordinator';

test('a purge waits for the old write and rejects every new write until durable acknowledgement', async () => {
  const coordinator = new TripVaultWriteCoordinator();
  const key = 'account:trip';
  const releaseOldWrite = coordinator.beginWrite(key);
  let purgeStarted = false;
  const purge = coordinator.beginPurge(key).then(() => {
    purgeStarted = true;
  });

  await Promise.resolve();
  expect(purgeStarted).toBe(false);
  expect(() => coordinator.beginWrite(key)).toThrow(TripVaultPurgeInProgressError);

  releaseOldWrite();
  await purge;
  expect(purgeStarted).toBe(true);
  expect(() => coordinator.beginWrite(key)).toThrow(TripVaultPurgeInProgressError);

  coordinator.endPurgeAttempt(key);
  coordinator.completePurge(key);
  const releaseNewWrite = coordinator.beginWrite(key);
  expect(releaseNewWrite).toEqual(expect.any(Function));
  releaseNewWrite();
});

test('a failed purge remains fenced for retry', async () => {
  const coordinator = new TripVaultWriteCoordinator();
  const key = 'account:trip';

  await coordinator.beginPurge(key);
  coordinator.endPurgeAttempt(key);

  expect(() => coordinator.beginWrite(key)).toThrow(TripVaultPurgeInProgressError);
  await coordinator.beginPurge(key);
  coordinator.endPurgeAttempt(key);
  expect(() => coordinator.beginWrite(key)).toThrow(TripVaultPurgeInProgressError);
});

test('durable acknowledgement waits for every concurrent purge attempt to finish', async () => {
  const coordinator = new TripVaultWriteCoordinator();
  const key = 'account:trip';

  await Promise.all([coordinator.beginPurge(key), coordinator.beginPurge(key)]);
  coordinator.endPurgeAttempt(key);
  coordinator.completePurge(key);
  expect(() => coordinator.beginWrite(key)).toThrow(TripVaultPurgeInProgressError);

  coordinator.endPurgeAttempt(key);
  const release = coordinator.beginWrite(key);
  release();
});

test('namespace cleanup waits for old writes, blocks stale writes and isolates another account', async () => {
  const coordinator = new VaultWriteCoordinator();
  const releaseOldWrite = coordinator.beginDocumentWrite('account-a', 'trip-a');
  let cleanupStarted = false;
  const cleanup = coordinator.beginNamespacePurge('account-a').then(() => {
    cleanupStarted = true;
  });

  await Promise.resolve();
  expect(cleanupStarted).toBe(false);
  expect(() => coordinator.beginDocumentWrite('account-a', 'trip-b')).toThrow(
    TripVaultPurgeInProgressError,
  );

  const releaseOtherAccount = coordinator.beginDocumentWrite('account-b', 'trip-a');
  releaseOtherAccount();

  releaseOldWrite();
  await cleanup;
  expect(cleanupStarted).toBe(true);
  expect(() => coordinator.beginDocumentWrite('account-a', 'trip-a')).toThrow(
    TripVaultPurgeInProgressError,
  );

  coordinator.finishNamespacePurge('account-a', true);
  const releaseFreshWrite = coordinator.beginDocumentWrite('account-a', 'trip-a');
  releaseFreshWrite();
});

test('installation-wide cleanup drains and fences every account write', async () => {
  const coordinator = new VaultWriteCoordinator();
  const releaseAccountA = coordinator.beginDocumentWrite('account-a', 'trip-a');
  const releaseAccountB = coordinator.beginDocumentWrite('account-b', 'trip-b');
  let purgeStarted = false;
  const purge = coordinator.beginGlobalPurge().then(() => {
    purgeStarted = true;
  });

  await Promise.resolve();
  expect(purgeStarted).toBe(false);
  expect(() => coordinator.beginDocumentWrite('account-c', 'trip-c')).toThrow(
    TripVaultPurgeInProgressError,
  );

  releaseAccountA();
  await Promise.resolve();
  expect(purgeStarted).toBe(false);
  releaseAccountB();
  await purge;
  expect(purgeStarted).toBe(true);
  expect(() => coordinator.beginDocumentWrite('account-a', 'trip-a')).toThrow(
    TripVaultPurgeInProgressError,
  );

  coordinator.finishGlobalPurge(true);
  const releaseFresh = coordinator.beginDocumentWrite('account-a', 'trip-a');
  releaseFresh();
});

test('temporary-view cleanup waits for plaintext creation and prevents late recreation', async () => {
  const coordinator = new TripVaultWriteCoordinator();
  const key = 'temporary-views';
  let plaintextExists = false;
  const releaseDecrypt = coordinator.beginWrite(key);
  const cleanup = (async () => {
    await coordinator.beginPurge(key);
    plaintextExists = false;
    coordinator.endPurgeAttempt(key);
    coordinator.completePurge(key);
  })();

  await Promise.resolve();
  plaintextExists = true;
  expect(() => coordinator.beginWrite(key)).toThrow(TripVaultPurgeInProgressError);
  releaseDecrypt();
  await cleanup;

  expect(plaintextExists).toBe(false);
  const releaseNextDecrypt = coordinator.beginWrite(key);
  releaseNextDecrypt();
});
