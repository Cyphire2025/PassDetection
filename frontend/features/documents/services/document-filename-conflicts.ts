import type { DocumentBatchReview } from "@/types/document-distribution.types";
import type { DocumentFilenameReplacement } from "./document-upload-batching";

export type DocumentFilenameConflictChoice = "replace" | "keep_original";

interface SavedFilenameDocument {
  id: string;
  updated_at: string | null;
}

export interface DocumentFilenameSelectionEntry {
  file: File;
  /** Index in the original selection, before any keep/replace decisions. */
  selectedIndex: number;
  filename: string;
  replaceDocumentIds: string[];
  replacementDocuments: DocumentFilenameReplacement["documents"];
}

export interface DocumentFilenameDecision {
  selectedIndex: number;
  filename: string;
  action: "add" | "replace" | "keep_original" | "superseded";
}

export interface DocumentFilenameResolutionPlan {
  files: File[];
  entries: DocumentFilenameSelectionEntry[];
  decisions: DocumentFilenameDecision[];
  skippedSelectedIndexes: number[];
  filenameReplacements: DocumentFilenameReplacement[];
}

export interface DocumentFilenameConflict {
  selectedIndex: number;
  filename: string;
  incomingFile: File;
  previousSelectedFile: File | null;
  previousSelectedIndex: number | null;
  savedDocumentCount: number;
  /** Includes the current conflict. */
  conflictNumber: number;
  totalConflicts: number;
  remainingConflictCount: number;
}

export interface DocumentFilenameConflictSession {
  files: readonly File[];
  cursor: number;
  savedByFilename: Map<string, SavedFilenameDocument[]>;
  acceptedByFilename: Map<string, DocumentFilenameSelectionEntry>;
  decisions: Map<number, DocumentFilenameDecision>;
  conflictIndexes: number[];
}

/** Mirror bounded_upload_filename: exact case, basename, whitespace and 255 code points. */
export function documentFilenameKey(value: string): string {
  const basename = (value || "document.pdf").replace(/\\/g, "/").split("/").at(-1) ?? "";
  // Python str.split also recognizes the information separators and NEL;
  // JavaScript \s instead includes BOM, which Python deliberately retains.
  const normalized = basename.replace(/\0/g, "")
    .split(/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/u)
    .filter(Boolean).join(" ");
  return Array.from(normalized).slice(0, 255).join("") || "document.pdf";
}

export function createDocumentFilenameConflictSession(
  files: readonly File[],
  review: DocumentBatchReview,
  groupId: string,
  documentType: string,
): DocumentFilenameConflictSession {
  if (review.group_id !== groupId || review.document_type !== documentType) {
    throw new Error("The saved PDF list changed. Refresh this document section and try again.");
  }
  const documents = new Map<string, { filename: string; updated_at: string | null }>();
  const remember = (document: {
    id: string;
    original_filename: string;
    document_type: string;
    updated_at?: string | null;
  }) => {
    if (document.document_type !== documentType) return;
    documents.set(document.id, {
      filename: documentFilenameKey(document.original_filename),
      updated_at: typeof document.updated_at === "string" ? document.updated_at : null,
    });
  };
  for (const row of review.review_rows) {
    if (row.document) remember(row.document);
    for (const document of row.documents) remember(document);
  }
  for (const document of review.unmatched_documents) remember(document);
  // Issue-only rows still represent saved PDFs. Missing versions deliberately
  // prevent replacement rather than silently overlooking those assignments.
  for (const issue of review.assignment_issues) {
    if (!documents.has(issue.document_id)) {
      documents.set(issue.document_id, {
        filename: documentFilenameKey(issue.original_filename), updated_at: null,
      });
    }
  }
  const savedByFilename = new Map<string, SavedFilenameDocument[]>();
  for (const [id, document] of documents) {
    const saved = savedByFilename.get(document.filename) ?? [];
    saved.push({ id, updated_at: document.updated_at });
    savedByFilename.set(document.filename, saved);
  }
  for (const saved of savedByFilename.values()) saved.sort((left, right) => left.id.localeCompare(right.id));
  const seen = new Set(savedByFilename.keys());
  const conflictIndexes: number[] = [];
  files.forEach((file, index) => {
    const filename = documentFilenameKey(file.name);
    if (seen.has(filename)) conflictIndexes.push(index);
    seen.add(filename);
  });
  return {
    files: [...files], cursor: 0, savedByFilename,
    acceptedByFilename: new Map(), decisions: new Map(), conflictIndexes,
  };
}

/** Advance ordinary files locally; return the next decision without performing any upload. */
export function nextDocumentFilenameConflict(
  session: DocumentFilenameConflictSession,
): DocumentFilenameConflict | null {
  while (session.cursor < session.files.length) {
    const selectedIndex = session.cursor;
    const file = session.files[selectedIndex];
    const filename = documentFilenameKey(file.name);
    const previous = session.acceptedByFilename.get(filename);
    const saved = session.savedByFilename.get(filename) ?? [];
    if (previous || saved.length > 0) {
      const conflictNumber = session.conflictIndexes.indexOf(selectedIndex) + 1;
      return {
        selectedIndex, filename, incomingFile: file,
        previousSelectedFile: previous?.file ?? null,
        previousSelectedIndex: previous?.selectedIndex ?? null,
        savedDocumentCount: saved.length,
        conflictNumber,
        totalConflicts: session.conflictIndexes.length,
        remainingConflictCount: session.conflictIndexes.length - conflictNumber,
      };
    }
    session.acceptedByFilename.set(filename, {
      file, selectedIndex, filename, replaceDocumentIds: [], replacementDocuments: [],
    });
    session.decisions.set(selectedIndex, { selectedIndex, filename, action: "add" });
    session.cursor += 1;
  }
  return null;
}

export function resolveDocumentFilenameConflict(
  session: DocumentFilenameConflictSession,
  choice: DocumentFilenameConflictChoice,
  applyToRemaining = false,
): DocumentFilenameConflict | null {
  let conflict = nextDocumentFilenameConflict(session);
  if (!conflict) return null;
  while (conflict) {
    const { selectedIndex, filename, incomingFile } = conflict;
    if (choice === "replace") {
      const saved = session.savedByFilename.get(filename) ?? [];
      const replacementDocuments = saved.map((document) => {
        if (!document.updated_at || !Number.isFinite(Date.parse(document.updated_at))) {
          throw new Error("The saved PDF details are out of date. Cancel, refresh this section, and check the files again.");
        }
        return { id: document.id, updated_at: document.updated_at };
      });
      const previous = session.acceptedByFilename.get(filename);
      if (previous) {
        session.decisions.set(previous.selectedIndex, {
          selectedIndex: previous.selectedIndex, filename, action: "superseded",
        });
      }
      session.acceptedByFilename.set(filename, {
        file: incomingFile, selectedIndex, filename,
        replaceDocumentIds: replacementDocuments.map((document) => document.id),
        replacementDocuments,
      });
    }
    session.decisions.set(selectedIndex, { selectedIndex, filename, action: choice });
    session.cursor += 1;
    conflict = nextDocumentFilenameConflict(session);
    if (!applyToRemaining) break;
  }
  return conflict;
}

export function finishDocumentFilenameConflicts(
  session: DocumentFilenameConflictSession,
): DocumentFilenameResolutionPlan {
  if (nextDocumentFilenameConflict(session)) {
    throw new Error("Choose what to do with each duplicate filename before checking the PDFs.");
  }
  const entries = [...session.acceptedByFilename.values()].sort((left, right) => left.selectedIndex - right.selectedIndex);
  const decisions = [...session.decisions.values()].sort((left, right) => left.selectedIndex - right.selectedIndex);
  return {
    entries,
    files: entries.map((entry) => entry.file),
    decisions,
    skippedSelectedIndexes: decisions.filter((decision) =>
      decision.action === "keep_original" || decision.action === "superseded",
    ).map((decision) => decision.selectedIndex),
    filenameReplacements: entries.filter((entry) => entry.replacementDocuments.length > 0).map((entry) => ({
      filename: entry.filename, documents: entry.replacementDocuments,
    })),
  };
}
