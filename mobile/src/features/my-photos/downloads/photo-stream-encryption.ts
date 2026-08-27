import {
  consumePlaintextStreamBounded,
  encodeVaultChunkFrame,
  type VaultChunkCipher,
  type VaultChunkRecovery,
} from '@/core/storage/vault-chunk-container';

export type PhotoPlaintextStreamReader = Readonly<{
  read: () => Promise<{ done: boolean; value?: Uint8Array | undefined }>;
  cancel?: (reason?: string) => Promise<unknown>;
}>;

/** Production stream-to-vault framing seam. Arbitrarily small or large native
 * network chunks are coalesced into the exact <=256 KiB authenticated frame
 * geometry used by quota and recovery calculations. */
export async function encryptBoundedPhotoStream(input: Readonly<{
  reader: PhotoPlaintextStreamReader;
  expectedBytes: number;
  cipher: VaultChunkCipher;
  additionalData: Uint8Array;
  recovery: VaultChunkRecovery;
  writeFrame: (frame: Uint8Array) => void | Promise<void>;
  assertActive: () => void;
  signal?: AbortSignal;
}>): Promise<number> {
  return consumePlaintextStreamBounded(
    {
      read: async () => {
        input.assertActive();
        const next = await input.reader.read();
        input.assertActive();
        return next;
      },
      ...(input.reader.cancel ? { cancel: input.reader.cancel } : {}),
    },
    input.expectedBytes,
    async (plaintext) => {
      input.assertActive();
      const frame = await encodeVaultChunkFrame(
        plaintext,
        input.cipher,
        input.additionalData,
        input.recovery.chunkCount,
        input.recovery.plaintextBytes,
      );
      input.assertActive();
      await input.writeFrame(frame);
      input.recovery.hasher.update(plaintext);
      input.recovery.plaintextBytes += plaintext.byteLength;
      input.recovery.chunkCount += 1;
    },
    input.signal,
  );
}
