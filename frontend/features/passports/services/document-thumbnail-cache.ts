import { fetchDocumentThumbnail } from "./document-thumbnail-loader";

type ThumbnailEntry = {
  controller: AbortController;
  promise: Promise<string>;
  objectUrl?: string;
};

/** In-memory previews owned by one page visit, never shared across sessions. */
export class DocumentThumbnailCache {
  private readonly entries = new Map<string, ThumbnailEntry>();

  peek(url: string): string | undefined {
    return this.entries.get(url)?.objectUrl;
  }

  load(url: string): Promise<string> {
    const cached = this.entries.get(url);
    if (cached) return cached.promise;

    const controller = new AbortController();
    const entry: ThumbnailEntry = {
      controller,
      promise: fetchDocumentThumbnail(url, controller.signal).then((image) => {
        // A request may finish after navigation even if its fetch ignored abort.
        if (controller.signal.aborted || this.entries.get(url) !== entry) {
          throw new DOMException("Page preview was released.", "AbortError");
        }
        entry.objectUrl = URL.createObjectURL(image);
        return entry.objectUrl;
      }).catch((error: unknown) => {
        if (this.entries.get(url) === entry) this.entries.delete(url);
        throw error;
      }),
    };
    this.entries.set(url, entry);
    return entry.promise;
  }

  invalidate(url: string): void {
    const entry = this.entries.get(url);
    if (!entry) return;
    this.entries.delete(url);
    entry.controller.abort();
    if (entry.objectUrl) URL.revokeObjectURL(entry.objectUrl);
  }

  clear(): void {
    for (const url of this.entries.keys()) this.invalidate(url);
  }
}
