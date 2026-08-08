import type { PassportDocumentImportPreview } from "../api/passports.api";

export function matchPreviewFiles(
  documents: PassportDocumentImportPreview["accepted_documents"],
  files: File[],
) {
  const queues = new Map<string, File[]>();
  for (const file of files) {
    const queue = queues.get(file.name) ?? [];
    queue.push(file);
    queues.set(file.name, queue);
  }
  const matches = new Map<
    PassportDocumentImportPreview["accepted_documents"][number],
    File
  >();
  for (const document of documents) {
    const file = queues.get(document.filename)?.shift();
    if (file) matches.set(document, file);
  }
  return matches;
}

export function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 MB";
  const mb = bytes / (1024 * 1024);
  if (mb < 1) return `${Math.round(bytes / 1024)} KB`;
  return `${mb.toFixed(mb >= 100 ? 0 : 1)} MB`;
}
