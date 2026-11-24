import type { DocumentVerificationResult } from "@/types/document-distribution.types";
import type { DocumentFilenameReplacement, DocumentStagingManifest } from "./document-upload-batching";

/** Manual review keeps the first exact-name replacement, including its identity. */
export function indexFirstFilenameReplacements(replacements: readonly DocumentFilenameReplacement[]) {
  const firstByFilename = new Map<string, DocumentFilenameReplacement>();
  for (const replacement of replacements) {
    const filename = replacement.filename;
    if (!firstByFilename.has(filename)) firstByFilename.set(filename, replacement);
  }
  return firstByFilename;
}

/** Attach every matching entry in input order, even when a name spans chunks. */
export function attachFilenameReplacements(
  manifest: DocumentStagingManifest,
  chunkIds: readonly string[],
  results: readonly DocumentVerificationResult[],
  replacements: readonly DocumentFilenameReplacement[],
) {
  const firstChunkIndex = new Map<string, number>();
  chunkIds.forEach((id, index) => {
    if (!firstChunkIndex.has(id)) firstChunkIndex.set(id, index);
  });
  const chunksByFilename = new Map<string, DocumentFilenameReplacement[][]>();
  for (const chunk of manifest.chunks) {
    const matchingReplacements: DocumentFilenameReplacement[] = [];
    chunk.filenameReplacements = matchingReplacements;
    const resultIndex = firstChunkIndex.get(chunk.chunkId);
    const acceptedNames = new Set(resultIndex === undefined ? [] : results[resultIndex]?.files
      .filter(file => file.accepted).map(file => file.filename));
    for (const filename of acceptedNames) {
      let chunks = chunksByFilename.get(filename);
      if (!chunks) {
        chunks = [];
        chunksByFilename.set(filename, chunks);
      }
      chunks.push(matchingReplacements);
    }
  }
  for (const replacement of replacements) {
    for (const matchingReplacements of chunksByFilename.get(replacement.filename) ?? []) {
      matchingReplacements.push(replacement);
    }
  }
}
