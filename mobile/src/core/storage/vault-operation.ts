export function documentAbortError(signal?: AbortSignal): Error {
  if (signal?.reason instanceof Error) return signal.reason;
  const error = new Error('Document download was cancelled.');
  error.name = 'AbortError';
  return error;
}

export function assertDocumentOperationActive(signal?: AbortSignal): void {
  if (signal?.aborted) throw documentAbortError(signal);
}

export async function waitForDocumentDelay(
  milliseconds: number,
  signal?: AbortSignal,
): Promise<void> {
  assertDocumentOperationActive(signal);
  if (!signal) {
    await new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
    return;
  }
  await new Promise<void>((resolve, reject) => {
    let settled = false;
    const finish = (operation: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal.removeEventListener('abort', onAbort);
      operation();
    };
    const onAbort = () => finish(() => reject(documentAbortError(signal)));
    const timer = setTimeout(() => finish(resolve), milliseconds);
    signal.addEventListener('abort', onAbort, { once: true });
    if (signal.aborted) onAbort();
  });
}
