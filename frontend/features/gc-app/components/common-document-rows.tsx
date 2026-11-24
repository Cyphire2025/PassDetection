"use client";

import { ArrowDown, ArrowUp, Eye, FileText, RefreshCw, Trash2 } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import type { GcCommonDocument } from "../types";
import { formatGcDateTime, gcPublicationState } from "../utils";

export function DocumentRows({
  now,
  documents,
  emptyMessage,
  isUpdating,
  previewingDocumentId,
  onPreview,
  onMove,
  onReplace,
  onSetPublished,
  onDelete,
}: {
  now: number;
  documents: GcCommonDocument[];
  emptyMessage: string;
  isUpdating: boolean;
  previewingDocumentId: string | null;
  onPreview: (document: GcCommonDocument) => Promise<void>;
  onMove: (index: number, direction: -1 | 1) => Promise<void>;
  onReplace: (document: GcCommonDocument) => void;
  onSetPublished: (documentId: string, published: boolean) => Promise<void>;
  onDelete: (document: GcCommonDocument) => void;
}) {
  if (documents.length === 0) {
    return <p className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">{emptyMessage}</p>;
  }

  return (
    <div className="space-y-3">
      {documents.map((document, index) => (
        <div key={document.id} className="flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <span className="rounded-lg bg-blue-50 p-2 text-blue-700"><FileText className="h-5 w-5" aria-hidden="true" /></span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <p className="truncate font-medium text-slate-900">{document.title}</p>
                <Badge variant={gcPublicationState(document, now).variant}>{gcPublicationState(document, now).label}</Badge>
                <Badge variant="default">v{document.version}</Badge>
              </div>
              <p className="mt-1 truncate text-xs text-slate-500">{document.filename} · Updated {formatGcDateTime(document.updated_at)}</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="secondary" size="sm" leftIcon={<Eye className="h-4 w-4" aria-hidden="true" />} isLoading={previewingDocumentId === document.id} onClick={() => void onPreview(document)}>Preview</Button>
            <Button type="button" variant="ghost" size="icon" aria-label={`Move ${document.title} up`} disabled={isUpdating || index === 0} onClick={() => void onMove(index, -1)}><ArrowUp className="h-4 w-4" /></Button>
            <Button type="button" variant="ghost" size="icon" aria-label={`Move ${document.title} down`} disabled={isUpdating || index === documents.length - 1} onClick={() => void onMove(index, 1)}><ArrowDown className="h-4 w-4" /></Button>
            <Button type="button" variant="secondary" size="sm" leftIcon={<RefreshCw className="h-4 w-4" />} onClick={() => onReplace(document)}>Replace</Button>
            <Button type="button" variant="secondary" size="sm" isLoading={isUpdating} onClick={() => void onSetPublished(document.id, !document.is_published)}>{document.is_published ? "Unpublish" : "Publish"}</Button>
            <Button type="button" variant="ghost" size="icon" className="text-red-600 hover:bg-red-50" aria-label={`Delete ${document.title}`} disabled={isUpdating} onClick={() => onDelete(document)}><Trash2 className="h-4 w-4" /></Button>
          </div>
        </div>
      ))}
    </div>
  );
}

