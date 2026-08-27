import {
  IncrementalSha256,
  VAULT_PLAINTEXT_CHUNK_BYTES,
  VaultChunkContainerError,
  chunkedVaultMagic,
  consumePlaintextStreamBounded,
  encodeVaultChunkFrame,
  maximumChunkedVaultBytes,
  recoverChunkedVault,
  type VaultChunkCipher,
} from '../vault-chunk-container';

class MemoryStore {
  constructor(public bytes: Uint8Array<ArrayBufferLike> = new Uint8Array()) {}

  append(value: Uint8Array): void {
    const combined = new Uint8Array(this.bytes.byteLength + value.byteLength);
    combined.set(this.bytes);
    combined.set(value, this.bytes.byteLength);
    this.bytes = combined;
  }

  reader() {
    return {
      size: this.bytes.byteLength,
      read: (offset: number, length: number) => this.bytes.slice(offset, offset + length),
    };
  }
}

function tag(plaintext: Uint8Array, aad: Uint8Array): Uint8Array {
  let state = 0;
  for (const value of aad) state = (state * 33 + value) & 0xff;
  for (const value of plaintext) state = (state * 33 + value) & 0xff;
  return Uint8Array.from({ length: 16 }, (_, index) => (state + index * 17) & 0xff);
}

function equal(left: Uint8Array, right: Uint8Array): boolean {
  return left.byteLength === right.byteLength
    && left.every((value, index) => value === right[index]);
}

function testCipher(): VaultChunkCipher {
  return {
    seal: async (plaintext, aad) => {
      const output = new Uint8Array(plaintext.byteLength + 28);
      output.fill(0x11, 0, 12);
      for (let index = 0; index < plaintext.byteLength; index += 1) {
        output[12 + index] = (plaintext[index] ?? 0) ^ 0xa5;
      }
      output.set(tag(plaintext, aad), 12 + plaintext.byteLength);
      return output;
    },
    open: async (sealed, aad) => {
      if (sealed.byteLength < 28) throw new Error('invalid sealed data');
      const plaintext = new Uint8Array(sealed.byteLength - 28);
      for (let index = 0; index < plaintext.byteLength; index += 1) {
        plaintext[index] = (sealed[12 + index] ?? 0) ^ 0xa5;
      }
      if (!equal(sealed.subarray(12 + plaintext.byteLength), tag(plaintext, aad))) {
        throw new Error('authentication failed');
      }
      return plaintext;
    },
  };
}

const AAD = new TextEncoder().encode(
  'account|33333333-3333-4333-8333-333333333333|44444444-4444-4444-8444-444444444444|1|'
  + 'a'.repeat(64),
);

test('incremental SHA-256 matches standard vectors across arbitrary updates', () => {
  expect(new IncrementalSha256().hexDigest()).toBe(
    'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
  );
  const hasher = new IncrementalSha256();
  hasher.update(new TextEncoder().encode('a'));
  hasher.update(new TextEncoder().encode('b'));
  hasher.update(new TextEncoder().encode('c'));
  expect(hasher.hexDigest()).toBe(
    'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
  );
});

test('recovers authenticated encrypted progress after a process restart', async () => {
  const cipher = testCipher();
  const store = new MemoryStore(chunkedVaultMagic());
  const first = Uint8Array.from([1, 2, 3]);
  const second = Uint8Array.from([4, 5]);
  store.append(await encodeVaultChunkFrame(first, cipher, AAD, 0, 0));

  // Simulate a new JS process: only app-private encrypted bytes survive.
  const recovered = await recoverChunkedVault(store.reader(), testCipher(), AAD, 5);
  expect(recovered.plaintextBytes).toBe(3);
  expect(recovered.chunkCount).toBe(1);

  store.append(await encodeVaultChunkFrame(
    second,
    cipher,
    AAD,
    recovered.chunkCount,
    recovered.plaintextBytes,
  ));
  const complete = await recoverChunkedVault(store.reader(), testCipher(), AAD, 5);
  expect(complete.plaintextBytes).toBe(5);
  expect(complete.hasher.hexDigest()).toBe(
    new IncrementalSha256().update(Uint8Array.from([1, 2, 3, 4, 5])).hexDigest(),
  );
  expect(store.bytes).not.toEqual(Uint8Array.from([1, 2, 3, 4, 5]));
});

test('rejects corrupted and truncated encrypted staging for fail-closed cleanup', async () => {
  const cipher = testCipher();
  const store = new MemoryStore(chunkedVaultMagic());
  store.append(await encodeVaultChunkFrame(Uint8Array.from([1, 2, 3]), cipher, AAD, 0, 0));

  const corrupted = new MemoryStore(store.bytes.slice());
  const corruptedIndex = corrupted.bytes.length - 1;
  corrupted.bytes.set(
    Uint8Array.of((corrupted.bytes[corruptedIndex] ?? 0) ^ 0xff),
    corruptedIndex,
  );
  await expect(recoverChunkedVault(corrupted.reader(), cipher, AAD, 3)).rejects.toBeInstanceOf(
    VaultChunkContainerError,
  );

  const truncated = new MemoryStore(store.bytes.slice(0, -1));
  await expect(recoverChunkedVault(truncated.reader(), cipher, AAD, 3)).rejects.toThrow(
    'invalid',
  );
});

test('bounds vault-controlled plaintext allocations to one encrypted chunk', async () => {
  const source = new Uint8Array(VAULT_PLAINTEXT_CHUNK_BYTES * 2 + 17);
  source.fill(7);
  let delivered = false;
  const reader = {
    read: jest.fn(async () => {
      if (delivered) return { done: true };
      delivered = true;
      return { done: false, value: source };
    }),
  };
  const committed: number[] = [];

  await expect(consumePlaintextStreamBounded(
    reader,
    source.byteLength,
    async (chunk) => {
      committed.push(chunk.byteLength);
    },
  )).resolves.toBe(source.byteLength);

  expect(committed).toEqual([
    VAULT_PLAINTEXT_CHUNK_BYTES,
    VAULT_PLAINTEXT_CHUNK_BYTES,
    17,
  ]);
  expect(Math.max(...committed)).toBe(VAULT_PLAINTEXT_CHUNK_BYTES);
});

test('coalesces many tiny network chunks into the frame count used by ciphertext quota', async () => {
  const total = VAULT_PLAINTEXT_CHUNK_BYTES * 2 + 17;
  const source = new Uint8Array(total);
  source.fill(9);
  let offset = 0;
  const reader = {
    read: jest.fn(async () => {
      if (offset >= source.byteLength) return { done: true };
      const next = source.subarray(offset, Math.min(source.byteLength, offset + 1_024));
      offset += next.byteLength;
      return { done: false, value: next };
    }),
  };
  const store = new MemoryStore(chunkedVaultMagic());
  let chunkIndex = 0;
  let plaintextOffset = 0;

  await expect(consumePlaintextStreamBounded(reader, total, async (plaintext) => {
    store.append(await encodeVaultChunkFrame(
      plaintext,
      testCipher(),
      AAD,
      chunkIndex,
      plaintextOffset,
    ));
    chunkIndex += 1;
    plaintextOffset += plaintext.byteLength;
  })).resolves.toBe(total);

  expect(chunkIndex).toBe(3);
  expect(store.bytes.byteLength).toBe(maximumChunkedVaultBytes(total));
  await expect(recoverChunkedVault(store.reader(), testCipher(), AAD, total))
    .resolves.toMatchObject({ plaintextBytes: total, chunkCount: 3 });
});
