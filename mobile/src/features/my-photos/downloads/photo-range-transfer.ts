import { MY_PHOTOS_NATIVE_RANGE_CHUNK_BYTES } from './download-policy';

export type PhotoByteRange = Readonly<{
  start: number;
  endInclusive: number;
  byteLength: number;
  requested: boolean;
}>;

export type PhotoRangeTransferRuntime = Readonly<{
  streamAndAppendEncrypted: (range: PhotoByteRange) => number | Promise<number>;
  progress?: (verifiedPlaintextBytes: number) => void | Promise<void>;
}>;

function assertOffset(value: number, label: string): void {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error(`${label} is invalid.`);
}

/** Coordinates resumable response streams. Bytes become authenticated vault
 * frames before a checkpoint advances; no plaintext filesystem target exists. */
export async function appendEncryptedPhotoRanges(
  expectedSizeBytes: number,
  recoveredPlaintextBytes: number,
  supportsRanges: boolean,
  runtime: PhotoRangeTransferRuntime,
  signal?: AbortSignal,
): Promise<number> {
  assertOffset(expectedSizeBytes, 'Expected photo size');
  assertOffset(recoveredPlaintextBytes, 'Recovered photo offset');
  if (expectedSizeBytes < 1 || recoveredPlaintextBytes > expectedSizeBytes) {
    throw new Error('Recovered photo offset exceeds its authorized size.');
  }
  if (!supportsRanges && recoveredPlaintextBytes !== 0) {
    throw new Error('A non-range photo transfer cannot resume.');
  }
  let verified = recoveredPlaintextBytes;
  while (verified < expectedSizeBytes) {
    if (signal?.aborted) throw signal.reason instanceof Error
      ? signal.reason
      : new Error('Photo operation cancelled.');
    const requested = supportsRanges;
    const endInclusive = requested
      ? Math.min(expectedSizeBytes - 1, verified + MY_PHOTOS_NATIVE_RANGE_CHUNK_BYTES - 1)
      : expectedSizeBytes - 1;
    const range: PhotoByteRange = Object.freeze({
      start: verified,
      endInclusive,
      byteLength: endInclusive - verified + 1,
      requested,
    });
    const appended = await runtime.streamAndAppendEncrypted(range);
    if (appended !== endInclusive + 1) {
      throw new Error('Encrypted photo checkpoint did not match its range boundary.');
    }
    verified = appended;
    await runtime.progress?.(verified);
  }
  return verified;
}
