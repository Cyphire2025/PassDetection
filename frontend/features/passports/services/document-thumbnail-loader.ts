import {
  acquireDocumentThumbnailSlot,
  isManagedDocumentThumbnail,
  pauseDocumentThumbnails,
  updateDocumentThumbnailAllowance,
} from "./document-thumbnail-scheduler";

function retryDelay(headers: Headers, attempt: number): number {
  const value = headers.get("Retry-After");
  if (value) {
    const seconds = Number(value);
    const delay = Number.isFinite(seconds)
      ? seconds * 1_000
      : Date.parse(value) - Date.now();
    if (Number.isFinite(delay) && delay > 0) return delay;
  }
  return Math.min(30_000, 1_000 * (2 ** attempt));
}

/** Read the response so throttling can pause the whole queue, not break an img. */
export async function fetchDocumentThumbnail(url: string, signal: AbortSignal): Promise<Blob> {
  if (!isManagedDocumentThumbnail(url)) throw new Error("Unsupported document thumbnail URL.");
  for (let attempt = 0; ; attempt += 1) {
    const release = await acquireDocumentThumbnailSlot(signal);
    try {
      const response = await fetch(url, {
        signal,
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
      });
      updateDocumentThumbnailAllowance(response.headers);
      if (response.status === 429 || response.status === 503) {
        pauseDocumentThumbnails(retryDelay(response.headers, attempt));
        await response.body?.cancel();
        if (attempt < 5) continue;
      }
      if (!response.ok) throw new Error(`Document preview failed (${response.status}).`);
      const image = await response.blob();
      if (!image.type.startsWith("image/")) throw new Error("Document preview was not an image.");
      return image;
    } finally {
      release();
    }
  }
}
