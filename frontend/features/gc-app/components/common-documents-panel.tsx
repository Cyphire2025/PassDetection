"use client";

import { ArrowDown, ArrowUp, Eye, FileText, RefreshCw, Trash2, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Button, Card, CardContent, Input } from "@/components/ui";
import type { CommonDocumentUpload, GcCommonDocument, GcDocumentCategory } from "../types";
import { formatGcDateTime, gcAppErrorMessage, toApiDateTime, toLocalDateTime } from "../utils";
import { GcAlert } from "./gc-app-feedback";
import { GcDialog } from "./gc-dialog";

const DOCUMENT_CATEGORIES: { value: GcDocumentCategory; label: string }[] = [
  { value: "itinerary_pdf", label: "Itinerary PDF" },
  { value: "travel_tips", label: "Travel tips" },
  { value: "common_instructions", label: "Common instructions" },
  { value: "destination", label: "Destination information" },
  { value: "emergency", label: "Emergency information" },
  { value: "hotel", label: "Hotel information" },
  { value: "flight_summary", label: "Flight summary" },
  { value: "meeting_point", label: "Meeting point" },
  { value: "dress_code", label: "Dress code" },
  { value: "baggage", label: "Baggage guidance" },
  { value: "other", label: "Other" },
];

export function CommonDocumentsPanel({
  documents,
  isUploading,
  isUpdating,
  previewingDocumentId,
  onUpload,
  onPreview,
  onSetPublished,
  onReorder,
  onDelete,
}: {
  documents: GcCommonDocument[];
  isUploading: boolean;
  isUpdating: boolean;
  previewingDocumentId: string | null;
  onUpload: (upload: CommonDocumentUpload) => Promise<void>;
  onPreview: (documentId: string) => Promise<Blob>;
  onSetPublished: (documentId: string, published: boolean) => Promise<void>;
  onReorder: (orderedDocumentIds: string[]) => Promise<void>;
  onDelete: (documentId: string) => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<GcDocumentCategory>("travel_tips");
  const [availableFrom, setAvailableFrom] = useState("");
  const [availableUntil, setAvailableUntil] = useState("");
  const [replaceDocument, setReplaceDocument] = useState<GcCommonDocument | null>(null);
  const [deleteDocument, setDeleteDocument] = useState<GcCommonDocument | null>(null);
  const [preview, setPreview] = useState<{ document: GcCommonDocument; url: string } | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const orderedDocuments = [...documents].sort((a, b) => a.sort_order - b.sort_order);

  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview.url);
  }, [preview]);

  const resetUpload = () => {
    setFile(null);
    setTitle("");
    setCategory("travel_tips");
    setAvailableFrom("");
    setAvailableUntil("");
    setReplaceDocument(null);
    setFileInputKey((value) => value + 1);
  };

  const upload = async () => {
    setError(null);
    if (!file || !title.trim()) {
      setError("Choose a PDF and enter a document title.");
      return;
    }
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      setError("Only PDF common documents are accepted.");
      return;
    }
    if (file.size > 25 * 1024 * 1024) {
      setError("The PDF exceeds the 25 MB dashboard upload limit.");
      return;
    }
    const from = toApiDateTime(availableFrom);
    const until = toApiDateTime(availableUntil);
    if (from && until && new Date(until) <= new Date(from)) {
      setError("Document availability expiry must be after its start time.");
      return;
    }
    try {
      await onUpload({
        file,
        title: title.trim(),
        category,
        available_from: from,
        available_until: until,
        replace_document_id: replaceDocument?.id,
      });
      resetUpload();
    } catch (uploadError) {
      setError(gcAppErrorMessage(uploadError, "The common document could not be uploaded."));
    }
  };

  const setPublished = async (documentId: string, published: boolean) => {
    setError(null);
    try {
      await onSetPublished(documentId, published);
    } catch (updateError) {
      setError(gcAppErrorMessage(updateError, "The document was not changed."));
    }
  };

  const openPreview = async (document: GcCommonDocument) => {
    setError(null);
    try {
      const blob = await onPreview(document.id);
      setPreview({ document, url: URL.createObjectURL(blob) });
    } catch (previewError) {
      setError(gcAppErrorMessage(previewError, "The document preview could not be opened."));
    }
  };

  const reorder = async (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= orderedDocuments.length) return;
    const next = [...orderedDocuments];
    [next[index], next[target]] = [next[target], next[index]];
    setError(null);
    try {
      await onReorder(next.map((document) => document.id));
    } catch (reorderError) {
      setError(gcAppErrorMessage(reorderError, "The document order was not changed."));
    }
  };

  return (
    <div className="space-y-4">
      {error && <GcAlert message={error} />}
      <Card>
        <CardContent className="space-y-4 p-5">
          <div>
            <h3 className="font-semibold text-slate-900">{replaceDocument ? `Replace ${replaceDocument.title}` : "Upload common group document"}</h3>
            <p className="mt-1 text-sm text-slate-500">Files remain draft-only until published. Mobile clients synchronize new versions without raw storage URLs.</p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Input label="Document title" value={title} onChange={(event) => setTitle(event.target.value)} required />
            <div className="flex flex-col gap-1.5">
              <label htmlFor="gc-document-category" className="text-sm font-medium text-slate-700">Category</label>
              <select id="gc-document-category" value={category} onChange={(event) => setCategory(event.target.value as GcDocumentCategory)} className="h-9 rounded-lg border border-slate-300 bg-white px-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600">
                {DOCUMENT_CATEGORIES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </div>
            <Input label="Available from" type="datetime-local" value={availableFrom} onChange={(event) => setAvailableFrom(event.target.value)} />
            <Input label="Available until" type="datetime-local" value={availableUntil} onChange={(event) => setAvailableUntil(event.target.value)} />
          </div>
          <label className="flex min-h-24 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-5 text-center hover:border-blue-400 hover:bg-blue-50/40 focus-within:ring-2 focus-within:ring-blue-600">
            <Upload className="h-5 w-5 text-slate-400" aria-hidden="true" />
            <span className="mt-2 text-sm font-medium text-slate-700">{file ? file.name : "Choose PDF"}</span>
            <span className="mt-1 text-xs text-slate-500">PDF only, up to 25 MB</span>
            <input
              key={fileInputKey}
              type="file"
              accept="application/pdf,.pdf"
              className="sr-only"
              onChange={(event) => {
                const nextFile = event.target.files?.[0] ?? null;
                setFile(nextFile);
                if (nextFile && !title) setTitle(nextFile.name.replace(/\.pdf$/i, ""));
              }}
            />
          </label>
          <div className="flex flex-wrap justify-end gap-2">
            {replaceDocument && <Button type="button" variant="secondary" onClick={resetUpload} disabled={isUploading}>Cancel replacement</Button>}
            <Button type="button" isLoading={isUploading} onClick={() => void upload()}>
              {replaceDocument ? "Upload replacement version" : "Upload as draft"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3 p-5">
          <div className="flex items-center justify-between">
            <div><h3 className="font-semibold text-slate-900">Common documents</h3><p className="mt-1 text-sm text-slate-500">Published files are visible only during their configured availability window.</p></div>
            <Badge variant="secondary">{documents.length}</Badge>
          </div>
          {documents.length === 0 ? (
            <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">No common documents uploaded.</p>
          ) : orderedDocuments.map((document, index) => (
            <div key={document.id} className="flex flex-col gap-4 rounded-xl border border-slate-200 p-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-w-0 items-start gap-3">
                <span className="rounded-lg bg-blue-50 p-2 text-blue-700"><FileText className="h-5 w-5" aria-hidden="true" /></span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate font-medium text-slate-900">{document.title}</p>
                    <Badge variant={document.is_published ? "success" : "outline"}>{document.is_published ? "Published" : "Draft"}</Badge>
                    <Badge variant="default">v{document.version}</Badge>
                  </div>
                  <p className="mt-1 truncate text-xs text-slate-500">{document.filename} · {categoryLabel(document.category)} · Updated {formatGcDateTime(document.updated_at)}</p>
                  {(document.available_from || document.available_until) && <p className="mt-1 text-xs text-slate-500">Available {document.available_from ? formatGcDateTime(document.available_from) : "immediately"} – {document.available_until ? formatGcDateTime(document.available_until) : "without expiry"}</p>}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  leftIcon={<Eye className="h-4 w-4" aria-hidden="true" />}
                  isLoading={previewingDocumentId === document.id}
                  onClick={() => void openPreview(document)}
                >
                  Preview
                </Button>
                <Button type="button" variant="ghost" size="icon" aria-label={`Move ${document.title} up`} disabled={isUpdating || index === 0} onClick={() => void reorder(index, -1)}><ArrowUp className="h-4 w-4" /></Button>
                <Button type="button" variant="ghost" size="icon" aria-label={`Move ${document.title} down`} disabled={isUpdating || index === orderedDocuments.length - 1} onClick={() => void reorder(index, 1)}><ArrowDown className="h-4 w-4" /></Button>
                <Button type="button" variant="secondary" size="sm" leftIcon={<RefreshCw className="h-4 w-4" />} onClick={() => {
                  setReplaceDocument(document);
                  setTitle(document.title);
                  setCategory(document.category);
                  setAvailableFrom(toLocalDateTime(document.available_from));
                  setAvailableUntil(toLocalDateTime(document.available_until));
                  window.scrollTo({ top: 0 });
                }}>Replace</Button>
                <Button type="button" variant="secondary" size="sm" isLoading={isUpdating} onClick={() => void setPublished(document.id, !document.is_published)}>{document.is_published ? "Unpublish" : "Publish"}</Button>
                <Button type="button" variant="ghost" size="icon" className="text-red-600 hover:bg-red-50" aria-label={`Delete ${document.title}`} onClick={() => setDeleteDocument(document)}><Trash2 className="h-4 w-4" /></Button>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <GcDialog
        open={Boolean(preview)}
        title={preview?.document.title ?? "Document preview"}
        description="Secure dashboard preview. The private storage address is never exposed."
        onClose={() => setPreview(null)}
        size="full"
      >
        {preview && (
          <iframe
            title={`${preview.document.title} PDF preview`}
            src={preview.url}
            className="h-[70dvh] w-full rounded-xl border border-slate-200 bg-slate-100"
          />
        )}
      </GcDialog>

      <GcDialog
        open={Boolean(deleteDocument)}
        title="Delete common document"
        description={deleteDocument ? `Delete ${deleteDocument.title}? The backend will publish a removal version so mobile devices can remove revoked offline copies.` : undefined}
        onClose={() => !isUpdating && setDeleteDocument(null)}
        closeDisabled={isUpdating}
        size="md"
        footer={(
          <>
            <Button type="button" variant="secondary" onClick={() => setDeleteDocument(null)} disabled={isUpdating}>Cancel</Button>
            <Button type="button" variant="danger" isLoading={isUpdating} onClick={() => {
              if (!deleteDocument) return;
              setError(null);
              void onDelete(deleteDocument.id).then(() => setDeleteDocument(null)).catch((deleteError: unknown) => setError(gcAppErrorMessage(deleteError, "The document could not be deleted.")));
            }}>Delete document</Button>
          </>
        )}
      >
        <p className="text-sm text-slate-600">Document history remains auditable. This action does not affect personal passenger documents.</p>
      </GcDialog>
    </div>
  );
}

function categoryLabel(category: GcDocumentCategory) {
  return DOCUMENT_CATEGORIES.find((option) => option.value === category)?.label ?? "Other";
}
