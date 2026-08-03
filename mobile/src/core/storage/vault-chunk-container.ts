const SHA256_BLOCK_BYTES = 64;
const VAULT_CHUNK_MAGIC = Uint8Array.from([0x47, 0x43, 0x56, 0x32, 0x43, 0x48, 0x4e, 0x4b]);
const FRAME_HEADER_BYTES = 8;
const AES_GCM_COMBINED_OVERHEAD_BYTES = 12 + 16;

export const VAULT_PLAINTEXT_CHUNK_BYTES = 256 * 1024;

const SHA256_INITIAL_STATE = Uint32Array.from([
  0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
  0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
]);

const SHA256_ROUND_CONSTANTS = Uint32Array.from([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
  0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
  0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
  0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
  0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
  0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

function rotateRight(value: number, amount: number): number {
  return (value >>> amount) | (value << (32 - amount));
}

/** Incremental SHA-256 for signed document verification without a whole-file buffer. */
export class IncrementalSha256 {
  private readonly state = new Uint32Array(SHA256_INITIAL_STATE);
  private readonly pending = new Uint8Array(SHA256_BLOCK_BYTES);
  private pendingLength = 0;
  private bytesHashed = 0;
  private finalized = false;

  update(input: Uint8Array): this {
    if (this.finalized) throw new Error('SHA-256 state is already finalized.');
    if (this.bytesHashed + input.byteLength > Number.MAX_SAFE_INTEGER) {
      throw new Error('SHA-256 input exceeded the supported size.');
    }
    this.bytesHashed += input.byteLength;
    let inputOffset = 0;
    if (this.pendingLength > 0) {
      const copied = Math.min(SHA256_BLOCK_BYTES - this.pendingLength, input.byteLength);
      this.pending.set(input.subarray(0, copied), this.pendingLength);
      this.pendingLength += copied;
      inputOffset += copied;
      if (this.pendingLength === SHA256_BLOCK_BYTES) {
        this.processBlock(this.pending, 0);
        this.pendingLength = 0;
      }
    }
    while (inputOffset + SHA256_BLOCK_BYTES <= input.byteLength) {
      this.processBlock(input, inputOffset);
      inputOffset += SHA256_BLOCK_BYTES;
    }
    if (inputOffset < input.byteLength) {
      const remainder = input.subarray(inputOffset);
      this.pending.set(remainder, 0);
      this.pendingLength = remainder.byteLength;
    }
    return this;
  }

  hexDigest(): string {
    if (this.finalized) throw new Error('SHA-256 state is already finalized.');
    this.finalized = true;
    const finalBlocks = new Uint8Array(
      this.pendingLength < 56 ? SHA256_BLOCK_BYTES : SHA256_BLOCK_BYTES * 2,
    );
    finalBlocks.set(this.pending.subarray(0, this.pendingLength));
    finalBlocks[this.pendingLength] = 0x80;
    const bitLengthHigh = Math.floor(this.bytesHashed / 0x20000000);
    const bitLengthLow = (this.bytesHashed << 3) >>> 0;
    const view = new DataView(finalBlocks.buffer);
    view.setUint32(finalBlocks.byteLength - 8, bitLengthHigh, false);
    view.setUint32(finalBlocks.byteLength - 4, bitLengthLow, false);
    for (let offset = 0; offset < finalBlocks.byteLength; offset += SHA256_BLOCK_BYTES) {
      this.processBlock(finalBlocks, offset);
    }
    return Array.from(this.state, (value) => value.toString(16).padStart(8, '0')).join('');
  }

  private processBlock(input: Uint8Array, offset: number): void {
    const words = new Uint32Array(64);
    const view = new DataView(input.buffer, input.byteOffset + offset, SHA256_BLOCK_BYTES);
    for (let index = 0; index < 16; index += 1) {
      words[index] = view.getUint32(index * 4, false);
    }
    for (let index = 16; index < 64; index += 1) {
      const word15 = words[index - 15] ?? 0;
      const word2 = words[index - 2] ?? 0;
      const sigma0 = rotateRight(word15, 7) ^ rotateRight(word15, 18) ^ (word15 >>> 3);
      const sigma1 = rotateRight(word2, 17) ^ rotateRight(word2, 19) ^ (word2 >>> 10);
      words[index] = (
        (words[index - 16] ?? 0) + sigma0 + (words[index - 7] ?? 0) + sigma1
      ) >>> 0;
    }

    let a = this.state[0] ?? 0;
    let b = this.state[1] ?? 0;
    let c = this.state[2] ?? 0;
    let d = this.state[3] ?? 0;
    let e = this.state[4] ?? 0;
    let f = this.state[5] ?? 0;
    let g = this.state[6] ?? 0;
    let h = this.state[7] ?? 0;
    for (let index = 0; index < 64; index += 1) {
      const sum1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const choice = (e & f) ^ (~e & g);
      const temp1 = (h + sum1 + choice + (SHA256_ROUND_CONSTANTS[index] ?? 0) + (words[index] ?? 0)) >>> 0;
      const sum0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (sum0 + majority) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }
    this.state[0] = ((this.state[0] ?? 0) + a) >>> 0;
    this.state[1] = ((this.state[1] ?? 0) + b) >>> 0;
    this.state[2] = ((this.state[2] ?? 0) + c) >>> 0;
    this.state[3] = ((this.state[3] ?? 0) + d) >>> 0;
    this.state[4] = ((this.state[4] ?? 0) + e) >>> 0;
    this.state[5] = ((this.state[5] ?? 0) + f) >>> 0;
    this.state[6] = ((this.state[6] ?? 0) + g) >>> 0;
    this.state[7] = ((this.state[7] ?? 0) + h) >>> 0;
  }
}

export class VaultChunkContainerError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'VaultChunkContainerError';
  }
}

export type VaultChunkCipher = {
  seal: (plaintext: Uint8Array, additionalData: Uint8Array) => Promise<Uint8Array>;
  open: (sealed: Uint8Array, additionalData: Uint8Array) => Promise<Uint8Array>;
};

export type VaultChunkReader = {
  size: number;
  read: (offset: number, length: number) => Uint8Array;
};

export type VaultChunkRecovery = {
  chunkCount: number;
  plaintextBytes: number;
  hasher: IncrementalSha256;
};

function equalBytes(left: Uint8Array, right: Uint8Array): boolean {
  if (left.byteLength !== right.byteLength) return false;
  let difference = 0;
  for (let index = 0; index < left.byteLength; index += 1) {
    difference |= (left[index] ?? 0) ^ (right[index] ?? 0);
  }
  return difference === 0;
}

function uint32(value: number): Uint8Array {
  const output = new Uint8Array(4);
  new DataView(output.buffer).setUint32(0, value, false);
  return output;
}

function frameAdditionalData(
  baseAdditionalData: Uint8Array,
  chunkIndex: number,
  plaintextOffset: number,
  plaintextLength: number,
): Uint8Array {
  const suffix = new TextEncoder().encode(
    `|gcv2|${chunkIndex}|${plaintextOffset}|${plaintextLength}`,
  );
  const output = new Uint8Array(baseAdditionalData.byteLength + suffix.byteLength);
  output.set(baseAdditionalData);
  output.set(suffix, baseAdditionalData.byteLength);
  return output;
}

export function chunkedVaultMagic(): Uint8Array {
  return new Uint8Array(VAULT_CHUNK_MAGIC);
}

export function isChunkedVaultPrefix(prefix: Uint8Array): boolean {
  return prefix.byteLength >= VAULT_CHUNK_MAGIC.byteLength
    && equalBytes(prefix.subarray(0, VAULT_CHUNK_MAGIC.byteLength), VAULT_CHUNK_MAGIC);
}

export async function encodeVaultChunkFrame(
  plaintext: Uint8Array,
  cipher: VaultChunkCipher,
  baseAdditionalData: Uint8Array,
  chunkIndex: number,
  plaintextOffset: number,
): Promise<Uint8Array> {
  if (plaintext.byteLength < 1 || plaintext.byteLength > VAULT_PLAINTEXT_CHUNK_BYTES) {
    throw new VaultChunkContainerError('Encrypted vault chunk had an invalid plaintext size.');
  }
  const sealed = await cipher.seal(
    plaintext,
    frameAdditionalData(
      baseAdditionalData,
      chunkIndex,
      plaintextOffset,
      plaintext.byteLength,
    ),
  );
  if (sealed.byteLength !== plaintext.byteLength + AES_GCM_COMBINED_OVERHEAD_BYTES) {
    throw new VaultChunkContainerError('Encrypted vault chunk had an invalid sealed size.');
  }
  const output = new Uint8Array(FRAME_HEADER_BYTES + sealed.byteLength);
  output.set(uint32(plaintext.byteLength), 0);
  output.set(uint32(sealed.byteLength), 4);
  output.set(sealed, FRAME_HEADER_BYTES);
  return output;
}

export async function recoverChunkedVault(
  reader: VaultChunkReader,
  cipher: VaultChunkCipher,
  baseAdditionalData: Uint8Array,
  expectedSizeBytes: number,
  onPlaintext?: (plaintext: Uint8Array) => void,
): Promise<VaultChunkRecovery> {
  if (reader.size < VAULT_CHUNK_MAGIC.byteLength) {
    throw new VaultChunkContainerError('Encrypted vault staging header was truncated.');
  }
  if (!isChunkedVaultPrefix(reader.read(0, VAULT_CHUNK_MAGIC.byteLength))) {
    throw new VaultChunkContainerError('Encrypted vault staging header was invalid.');
  }
  const hasher = new IncrementalSha256();
  let cursor = VAULT_CHUNK_MAGIC.byteLength;
  let plaintextBytes = 0;
  let chunkCount = 0;
  while (cursor < reader.size) {
    if (reader.size - cursor < FRAME_HEADER_BYTES) {
      throw new VaultChunkContainerError('Encrypted vault staging frame was truncated.');
    }
    const header = reader.read(cursor, FRAME_HEADER_BYTES);
    if (header.byteLength !== FRAME_HEADER_BYTES) {
      throw new VaultChunkContainerError('Encrypted vault staging frame was truncated.');
    }
    const view = new DataView(header.buffer, header.byteOffset, header.byteLength);
    const plaintextLength = view.getUint32(0, false);
    const sealedLength = view.getUint32(4, false);
    if (
      plaintextLength < 1
      || plaintextLength > VAULT_PLAINTEXT_CHUNK_BYTES
      || sealedLength !== plaintextLength + AES_GCM_COMBINED_OVERHEAD_BYTES
      || plaintextBytes + plaintextLength > expectedSizeBytes
      || cursor + FRAME_HEADER_BYTES + sealedLength > reader.size
    ) {
      throw new VaultChunkContainerError('Encrypted vault staging frame was invalid.');
    }
    const sealed = reader.read(cursor + FRAME_HEADER_BYTES, sealedLength);
    if (sealed.byteLength !== sealedLength) {
      throw new VaultChunkContainerError('Encrypted vault staging frame was truncated.');
    }
    let plaintext: Uint8Array;
    try {
      plaintext = await cipher.open(
        sealed,
        frameAdditionalData(
          baseAdditionalData,
          chunkCount,
          plaintextBytes,
          plaintextLength,
        ),
      );
    } catch {
      throw new VaultChunkContainerError('Encrypted vault staging authentication failed.');
    }
    if (plaintext.byteLength !== plaintextLength) {
      throw new VaultChunkContainerError('Encrypted vault staging plaintext length was invalid.');
    }
    hasher.update(plaintext);
    onPlaintext?.(plaintext);
    plaintextBytes += plaintextLength;
    chunkCount += 1;
    cursor += FRAME_HEADER_BYTES + sealedLength;
  }
  return { chunkCount, plaintextBytes, hasher };
}

type StreamReader = {
  read: () => Promise<{ done: boolean; value?: Uint8Array | undefined }>;
  cancel?: (reason?: string) => Promise<unknown>;
};

/** Consume an Expo fetch stream in fixed-size plaintext windows. */
export async function consumePlaintextStreamBounded(
  reader: StreamReader,
  maximumBytes: number,
  commit: (plaintext: Uint8Array) => Promise<void>,
  signal?: AbortSignal,
): Promise<number> {
  if (!Number.isSafeInteger(maximumBytes) || maximumBytes < 0) {
    throw new VaultChunkContainerError('Document stream limit was invalid.');
  }
  let committedBytes = 0;
  let pendingLength = 0;
  let pending = new Uint8Array(Math.min(VAULT_PLAINTEXT_CHUNK_BYTES, maximumBytes || 1));
  while (true) {
    if (signal?.aborted) {
      await reader.cancel?.('Document download was cancelled.').catch(() => undefined);
      throw signal.reason instanceof Error ? signal.reason : new Error('Document download was cancelled.');
    }
    const next = await reader.read();
    if (next.done) break;
    if (!next.value?.byteLength) continue;
    let sourceOffset = 0;
    while (sourceOffset < next.value.byteLength) {
      const available = pending.byteLength - pendingLength;
      const copied = Math.min(available, next.value.byteLength - sourceOffset);
      if (committedBytes + pendingLength + copied > maximumBytes) {
        await reader.cancel?.('Document exceeded its allowed size.').catch(() => undefined);
        throw new VaultChunkContainerError('Downloaded document exceeded its allowed size.');
      }
      pending.set(next.value.subarray(sourceOffset, sourceOffset + copied), pendingLength);
      pendingLength += copied;
      sourceOffset += copied;
      if (pendingLength === pending.byteLength) {
        await commit(pending);
        committedBytes += pendingLength;
        pendingLength = 0;
        const remaining = maximumBytes - committedBytes;
        pending = new Uint8Array(Math.min(VAULT_PLAINTEXT_CHUNK_BYTES, Math.max(remaining, 1)));
      }
    }
  }
  if (pendingLength > 0) {
    await commit(pending.subarray(0, pendingLength));
    committedBytes += pendingLength;
  }
  return committedBytes;
}

export function maximumChunkedVaultBytes(plaintextBytes: number): number {
  const chunks = Math.ceil(plaintextBytes / VAULT_PLAINTEXT_CHUNK_BYTES);
  return VAULT_CHUNK_MAGIC.byteLength
    + plaintextBytes
    + chunks * (FRAME_HEADER_BYTES + AES_GCM_COMBINED_OVERHEAD_BYTES);
}
