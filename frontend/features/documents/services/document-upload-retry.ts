import type { ApiError } from "@/lib/api/client";

export async function retryTransientDocumentChunk<T>(
  operation: () => Promise<T>,
  signal?: AbortSignal,
): Promise<T> {
  let attempt = 0;
  while (true) {
    if (signal?.aborted) throw documentUploadAbortError(signal.reason);
    try {
      return await operation();
    } catch (error) {
      if (signal?.aborted) throw documentUploadAbortError(signal.reason);
      if (attempt >= 2 || !isTransientDocumentUploadError(error)) throw error;
      attempt += 1;
      await abortableDocumentRetryDelay(400 * attempt, signal);
    }
  }
}

function abortableDocumentRetryDelay(delayMs: number, signal?: AbortSignal) {
  if (!signal) {
    return new Promise<void>((resolve) => globalThis.setTimeout(resolve, delayMs));
  }
  if (signal.aborted) return Promise.reject(documentUploadAbortError(signal.reason));
  return new Promise<void>((resolve, reject) => {
    const timeout = globalThis.setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, delayMs);
    const abort = () => {
      globalThis.clearTimeout(timeout);
      reject(documentUploadAbortError(signal.reason));
    };
    signal.addEventListener("abort", abort, { once: true });
  });
}

function documentUploadAbortError(reason: unknown) {
  if (reason instanceof Error) return reason;
  const error = new Error("The document operation was cancelled.");
  error.name = "AbortError";
  return error;
}

function isTransientDocumentUploadError(error: unknown): boolean {
  const code = (error as Partial<ApiError> | null)?.code;
  return (
    code === "NETWORK_ERROR" ||
    code === "REQUEST_TIMEOUT" ||
    code === "HTTP_429" ||
    code === "HTTP_502" ||
    code === "HTTP_503" ||
    code === "HTTP_504"
  );
}
