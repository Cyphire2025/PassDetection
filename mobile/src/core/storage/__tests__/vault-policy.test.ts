import {
  assertVaultFreeSpace,
  requiredVaultFreeSpace,
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
  expect(() => validateVaultDocument({ ...valid, expectedSizeBytes: 26 * 1024 * 1024 })).toThrow('size');
});

test('requires an exact numeric Content-Length before allocation', () => {
  expect(() => validateDeclaredDocumentLength('1024', 1024)).not.toThrow();
  expect(() => validateDeclaredDocumentLength(null, 1024)).toThrow('content length');
  expect(() => validateDeclaredDocumentLength('1025', 1024)).toThrow('metadata');
  expect(() => validateDeclaredDocumentLength('1e3', 1000)).toThrow('content length');
});

test('keeps disk headroom for plaintext, ciphertext and atomic temporary data', () => {
  const required = requiredVaultFreeSpace(valid.expectedSizeBytes);
  expect(() => assertVaultFreeSpace(required, valid.expectedSizeBytes)).not.toThrow();
  expect(() => assertVaultFreeSpace(required - 1, valid.expectedSizeBytes)).toThrow('free device storage');
  expect(() => assertVaultFreeSpace(undefined, valid.expectedSizeBytes)).not.toThrow();
});
