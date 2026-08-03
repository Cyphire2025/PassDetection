import {
  assertVaultFreeSpace,
  assertManagedTemporaryViewUri,
  isFreshResumableVaultStagingEntry,
  isManagedVaultFileName,
  offlinePrefetchConcurrency,
  planVaultOrphanCleanup,
  requiredVaultFreeSpace,
  shouldDiscardManagedCiphertextAfterFailure,
  validateAuthorizedDocumentPath,
  validateDeclaredDocumentLength,
  validateVaultDocument,
} from '../vault-policy';

const valid = {
  namespace: '11111111-1111-4111-8111-111111111111.22222222-2222-4222-8222-222222222222',
  tripId: '33333333-3333-4333-8333-333333333333',
  documentId: '44444444-4444-4444-8444-444444444444',
  version: 1,
  checksumSha256: 'a'.repeat(64),
  expectedSizeBytes: 1024,
  contentType: 'application/pdf',
};

test('accepts only bounded, typed, UUID-scoped vault documents', () => {
  expect(() => validateVaultDocument(valid)).not.toThrow();
  expect(() => validateVaultDocument({ ...valid, documentId: '../passport.pdf' })).toThrow('identity');
  expect(() => validateVaultDocument({ ...valid, contentType: 'text/html' })).toThrow('type');
  expect(() => validateVaultDocument({ ...valid, contentType: 'application/octet-stream' })).toThrow('type');
  expect(() => validateVaultDocument({ ...valid, expectedSizeBytes: 26 * 1024 * 1024 })).toThrow('size');
});

test('accepts omitted Content-Length but rejects invalid or mismatched declarations', () => {
  expect(() => validateDeclaredDocumentLength('1024', 1024)).not.toThrow();
  expect(() => validateDeclaredDocumentLength(null, 1024)).not.toThrow();
  expect(() => validateDeclaredDocumentLength('1025', 1024)).toThrow('metadata');
  expect(() => validateDeclaredDocumentLength('1e3', 1000)).toThrow('content length');
});

test('binds document grants to the exact requested API route and version', () => {
  const route = `/api/v1/mobile/trips/${valid.tripId}/documents/${valid.documentId}/content?version=1`;
  expect(() => validateAuthorizedDocumentPath(route, valid.tripId, valid.documentId, 1)).not.toThrow();
  expect(() => validateAuthorizedDocumentPath(
    route.replace('/api/v1/', '/untrusted/api/v1/'),
    valid.tripId,
    valid.documentId,
    1,
  )).toThrow('requested document');
  expect(() => validateAuthorizedDocumentPath(
    route.replace(valid.documentId, '55555555-5555-4555-8555-555555555555'),
    valid.tripId,
    valid.documentId,
    1,
  )).toThrow('requested document');
  expect(() => validateAuthorizedDocumentPath(
    route.replace('version=1', 'version=2'),
    valid.tripId,
    valid.documentId,
    1,
  )).toThrow('requested version');
});

test('keeps disk headroom for plaintext, ciphertext and atomic temporary data', () => {
  const required = requiredVaultFreeSpace(valid.expectedSizeBytes);
  expect(() => assertVaultFreeSpace(required, valid.expectedSizeBytes)).not.toThrow();
  expect(() => assertVaultFreeSpace(required - 1, valid.expectedSizeBytes)).toThrow('free device storage');
  expect(() => assertVaultFreeSpace(undefined, valid.expectedSizeBytes)).not.toThrow();
});

test('serializes large encrypted-file prefetches to bound transient memory', () => {
  expect(offlinePrefetchConcurrency([1024, 2 * 1024 * 1024])).toBe(2);
  expect(offlinePrefetchConcurrency([1024, 8 * 1024 * 1024])).toBe(1);
  expect(offlinePrefetchConcurrency([null, undefined])).toBe(2);
});

describe('temporary plaintext cleanup boundary', () => {
  const root = 'file:///private/cache/gc-secure-view-v1';
  const validName = '44444444-4444-4444-8444-444444444444.pdf';

  test('accepts only an immediate managed temporary-view filename', () => {
    expect(() => assertManagedTemporaryViewUri(root, `${root}/${validName}`)).not.toThrow();
    expect(() => assertManagedTemporaryViewUri(root, `${root}-sibling/${validName}`)).toThrow('untrusted');
    expect(() => assertManagedTemporaryViewUri(root, `${root}/../${validName}`)).toThrow('untrusted');
    expect(() => assertManagedTemporaryViewUri(root, `${root}\\${validName}`)).toThrow('untrusted');
    expect(() => assertManagedTemporaryViewUri(root, `${root}/nested/${validName}`)).toThrow('untrusted');
    expect(() => assertManagedTemporaryViewUri(root, `${root}/${validName}.bak`)).toThrow('untrusted');
  });
});

test('preserves resumable and final ciphertext when validation is cancelled', () => {
  const controller = new AbortController();
  expect(shouldDiscardManagedCiphertextAfterFailure(controller.signal)).toBe(true);
  controller.abort();
  expect(shouldDiscardManagedCiphertextAfterFailure(controller.signal)).toBe(false);
});

describe('vault crash recovery policy', () => {
  const root = 'file:///private/gc-vault/account-a/33333333-3333-4333-8333-333333333333';
  const documentA = '44444444-4444-4444-8444-444444444444';
  const documentB = '55555555-5555-4555-8555-555555555555';
  const checksumA = 'a'.repeat(64);
  const checksumB = 'b'.repeat(64);
  const registered = `${root}/${documentA}.1.${checksumA}.gcv`;
  const orphanFinal = `${root}/${documentA}.2.${checksumB}.gcv`;
  const activeStaging = `${root}/.${documentB}.1.66666666-6666-4666-8666-666666666666.tmp`;
  const crashedStaging = `${root}/.${documentB}.1.77777777-7777-4777-8777-777777777777.tmp`;
  const durableStaging = `${root}/.${documentB}.1.${checksumB}.resume.tmp`;

  test('removes only unregistered managed ciphertext after a crash', () => {
    const entries = [registered, orphanFinal, activeStaging, crashedStaging].map((uri) => ({
      uri,
      name: uri.slice(root.length + 1),
    }));

    expect(planVaultOrphanCleanup(root, entries, [registered], [activeStaging])).toEqual([
      orphanFinal,
      crashedStaging,
    ]);
    expect(isManagedVaultFileName(`${documentA}.1.gcv`)).toBe(true);
    expect(isManagedVaultFileName('unrelated-user-file.pdf')).toBe(false);
  });

  test('fails closed when a database registration points at another account or trip', () => {
    const otherAccount = registered.replace('/account-a/', '/account-b/');
    expect(() => planVaultOrphanCleanup(
      root,
      [{ uri: orphanFinal, name: orphanFinal.slice(root.length + 1) }],
      [otherAccount],
    )).toThrow('account and trip boundary');
  });

  test('does not treat prefix-confusable trip paths as children', () => {
    const adjacentTrip = `${root}-other/${documentA}.1.${checksumA}.gcv`;
    expect(() => planVaultOrphanCleanup(root, [], [adjacentTrip])).toThrow('account and trip boundary');
  });

  test('preserves unknown files for forward compatibility', () => {
    const unknown = `${root}/future-index-v2.bin`;
    expect(planVaultOrphanCleanup(
      root,
      [{ uri: unknown, name: 'future-index-v2.bin' }],
      [],
    )).toEqual([]);
  });

  test('retains fresh encrypted resume staging and removes it after the recovery window', () => {
    const now = Date.UTC(2026, 7, 3, 10, 0, 0);
    const entry = {
      uri: durableStaging,
      name: durableStaging.slice(root.length + 1),
      lastModified: now - 60_000,
    };

    expect(isFreshResumableVaultStagingEntry(entry, now)).toBe(true);
    expect(planVaultOrphanCleanup(root, [entry], [], [durableStaging])).toEqual([]);
    const staleEntry = {
      ...entry,
      lastModified: now - (25 * 60 * 60 * 1_000),
    };
    expect(isFreshResumableVaultStagingEntry(staleEntry, now)).toBe(false);
    expect(planVaultOrphanCleanup(root, [staleEntry], [])).toEqual([durableStaging]);
    expect(isManagedVaultFileName(entry.name)).toBe(true);
  });
});
