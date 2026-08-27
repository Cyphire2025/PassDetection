import {
  IncrementalSha256,
  VAULT_PLAINTEXT_CHUNK_BYTES,
  chunkedVaultMagic,
  maximumChunkedVaultBytes,
  type VaultChunkCipher,
} from '@/core/storage/vault-chunk-container';

import { encryptBoundedPhotoStream } from '../photo-stream-encryption';

const cipher: VaultChunkCipher = {
  seal: async (plaintext) => {
    const sealed = new Uint8Array(plaintext.byteLength + 28);
    sealed.set(plaintext, 12);
    return sealed;
  },
  open: async (sealed) => sealed.subarray(12, sealed.byteLength - 16),
};

it('coalesces tiny native chunks through the production photo callback into quota-bounded frames', async () => {
  const total = VAULT_PLAINTEXT_CHUNK_BYTES * 2 + 17;
  const source = new Uint8Array(total);
  source.fill(0x5a);
  let offset = 0;
  const frames: Uint8Array[] = [];
  const recovery = {
    chunkCount: 0,
    plaintextBytes: 0,
    hasher: new IncrementalSha256(),
  };
  const assertActive = jest.fn();

  await expect(encryptBoundedPhotoStream({
    reader: {
      read: async () => {
        if (offset >= source.byteLength) return { done: true };
        const value = source.subarray(offset, Math.min(source.byteLength, offset + 1_024));
        offset += value.byteLength;
        return { done: false, value };
      },
    },
    expectedBytes: total,
    cipher,
    additionalData: new TextEncoder().encode('account-scoped-photo'),
    recovery,
    writeFrame: (frame) => { frames.push(frame); },
    assertActive,
  })).resolves.toBe(total);

  expect(recovery).toMatchObject({ chunkCount: 3, plaintextBytes: total });
  expect(
    chunkedVaultMagic().byteLength
      + frames.reduce((bytes, frame) => bytes + frame.byteLength, 0),
  ).toBe(maximumChunkedVaultBytes(total));
  expect(assertActive).toHaveBeenCalled();
});

it('does not commit a short EOF tail and resumes within the original frame quota', async () => {
  const total = VAULT_PLAINTEXT_CHUNK_BYTES + 100 * 1024;
  const frames: Uint8Array[] = [];
  const recovery = {
    chunkCount: 0,
    plaintextBytes: 0,
    hasher: new IncrementalSha256(),
  };
  const firstPayload = new Uint8Array(VAULT_PLAINTEXT_CHUNK_BYTES + 50 * 1024);
  let firstRead = false;
  const firstCancel = jest.fn(async () => undefined);

  await expect(encryptBoundedPhotoStream({
    reader: {
      read: async () => {
        if (firstRead) return { done: true };
        firstRead = true;
        return { done: false, value: firstPayload };
      },
      cancel: firstCancel,
    },
    expectedBytes: total,
    cipher,
    additionalData: new TextEncoder().encode('account-scoped-photo'),
    recovery,
    writeFrame: (frame) => { frames.push(frame); },
    assertActive: () => undefined,
  })).rejects.toThrow('shorter than');

  expect(recovery).toMatchObject({
    chunkCount: 1,
    plaintextBytes: VAULT_PLAINTEXT_CHUNK_BYTES,
  });
  expect(firstCancel).toHaveBeenCalled();

  let resumedRead = false;
  await expect(encryptBoundedPhotoStream({
    reader: {
      read: async () => {
        if (resumedRead) return { done: true };
        resumedRead = true;
        return { done: false, value: new Uint8Array(100 * 1024) };
      },
    },
    expectedBytes: 100 * 1024,
    cipher,
    additionalData: new TextEncoder().encode('account-scoped-photo'),
    recovery,
    writeFrame: (frame) => { frames.push(frame); },
    assertActive: () => undefined,
  })).resolves.toBe(100 * 1024);

  expect(recovery).toMatchObject({ chunkCount: 2, plaintextBytes: total });
  expect(
    chunkedVaultMagic().byteLength
      + frames.reduce((bytes, frame) => bytes + frame.byteLength, 0),
  ).toBe(maximumChunkedVaultBytes(total));
});

it.each(['overflow', 'reader_error'] as const)('cancels the native reader after %s', async (failure) => {
  const cancel = jest.fn(async () => undefined);
  await expect(encryptBoundedPhotoStream({
    reader: {
      read: failure === 'overflow'
        ? async () => ({ done: false, value: new Uint8Array(11) })
        : async () => { throw new TypeError('reader failed'); },
      cancel,
    },
    expectedBytes: 10,
    cipher,
    additionalData: new Uint8Array(),
    recovery: {
      chunkCount: 0,
      plaintextBytes: 0,
      hasher: new IncrementalSha256(),
    },
    writeFrame: () => undefined,
    assertActive: () => undefined,
  })).rejects.toThrow(failure === 'overflow' ? 'exceeded' : 'reader failed');
  expect(cancel).toHaveBeenCalled();
});
