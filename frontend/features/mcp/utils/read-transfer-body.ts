/** A transfer route owns its bounded response reader until completion or abort. */
export async function readTransferBody(
  body: ReadableStream<Uint8Array> | null,
  byteSize: number,
  mediaType: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const reader = body?.getReader();
  if (!reader) throw new Error("The file could not be read. Try the download again.");
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let size = 0;
  const abort = () => { void reader.cancel().catch(() => undefined); };
  signal?.addEventListener("abort", abort, { once: true });
  try {
    signal?.throwIfAborted();
    while (true) {
      const { done, value } = await reader.read();
      signal?.throwIfAborted();
      if (done) break;
      size += value.byteLength;
      if (size > byteSize) throw new Error("The returned file is larger than this transfer allows.");
      chunks.push(new Uint8Array(value));
    }
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    throw error;
  } finally {
    signal?.removeEventListener("abort", abort);
    reader.releaseLock();
  }
  return new Blob(chunks, { type: mediaType });
}
