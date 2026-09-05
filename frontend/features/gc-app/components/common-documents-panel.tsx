"use client";

import { ArrowDown, ArrowUp, Eye, FileText, RefreshCw, Trash2, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Card, CardContent, Input } from "@/components/ui";
import type { CommonDocumentUpload, GcCommonDocument, GcDocumentCategory } from "../types";
import { formatGcDateTime, gcAppErrorMessage } from "../utils";
import { GcAlert } from "./gc-app-feedback";
import { GcDialog } from "./gc-dialog";
import { GcSelect } from "./gc-select";

const ITINERARY_CATEGORY: GcDocumentCategory = "itinerary_pdf";
const OTHER_DOCUMENT_CATEGORIES: { value: GcDocumentCategory; label: string }[] = [
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
  const [replaceDocument, setReplaceDocument] = useState<GcCommonDocument | null>(null);
  const [deleteDocument, setDeleteDocument] = useState<GcCommonDocument | null>(null);
  const [preview, setPreview] = useState<{ document: GcCommonDocument; url: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const orderedDocuments = useMemo(
    () => [...documents].sort((a, b) => a.sort_order - b.sort_order || a.title.localeCompare(b.title)),
    [documents],
  );
  const { itineraryDocuments, otherGroups } = useMemo(() => {
    const itinerary: GcCommonDocument[] = [];
    const byCategory = new Map<GcDocumentCategory, GcCommonDocument[]>(
      OTHER_DOCUMENT_CATEGORIES.map((category) => [category.value, []]),
    );
    for (const item of orderedDocuments) {
      if (item.category === ITINERARY_CATEGORY) {
        itinerary.push(item);
      } else {
        byCategory.get(item.category)?.push(item);
      }
    }
    return {
      itineraryDocuments: itinerary,
      otherGroups: OTHER_DOCUMENT_CATEGORIES.map((category) => ({
        ...category,
        documents: byCategory.get(category.value) ?? [],
      })),
    };
  }, [orderedDocuments]);
  const visibleOtherGroups = otherGroups.filter((group) => group.documents.length > 0);
  const latestItinerary = itineraryDocuments.reduce<GcCommonDocument | null>(
    (latest, document) => (!latest || document.version > latest.version ? document : latest),
    null,
  );
  const itineraryReplacement = replaceDocument?.category === ITINERARY_CATEGORY
    ? replaceDocument
    : latestItinerary;
  const otherReplacement = replaceDocument?.category !== ITINERARY_CATEGORY
    ? replaceDocument
    : null;

  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview.url);
  }, [preview]);

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

  const startReplacement = (document: GcCommonDocument) => {
    setError(null);
    setReplaceDocument(document);
    const targetId = document.category === ITINERARY_CATEGORY ? "gc-itinerary-upload" : "gc-other-document-upload";
    requestAnimationFrame(() => documentById(targetId)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  const reorderCollection = async (
    collection: GcCommonDocument[],
    index: number,
    direction: -1 | 1,
    category: GcDocumentCategory,
  ) => {
    const target = index + direction;
    if (target < 0 || target >= collection.length) return;
    const nextCollection = [...collection];
    [nextCollection[index], nextCollection[target]] = [nextCollection[target], nextCollection[index]];
    const nextItinerary = category === ITINERARY_CATEGORY ? nextCollection : itineraryDocuments;
    const nextOthers = otherGroups.flatMap((group) => (
      group.value === category ? nextCollection : group.documents
    ));
    setError(null);
    try {
      await onReorder([...nextItinerary, ...nextOthers].map((document) => document.id));
    } catch (reorderError) {
      setError(gcAppErrorMessage(reorderError, "The document order was not changed."));
    }
  };

  return (
    <div className="space-y-5">
      {error && <GcAlert message={error} />}

      <Card>
        <CardContent className="space-y-5 p-5">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">Itinerary</h3>
            <p className="mt-1 text-sm text-slate-500">Published itineraries appear under Itinerary in the app. Publish a replacement to update the document.</p>
          </div>
          <DocumentUploadForm
            key={`itinerary-${itineraryReplacement?.id ?? "new"}`}
            id="gc-itinerary-upload"
            fixedCategory={ITINERARY_CATEGORY}
            fixedTitle="Itinerary"
            replaceDocument={itineraryReplacement}
            isUploading={isUploading}
            onUpload={onUpload}
            onComplete={() => setReplaceDocument(null)}
            onError={setError}
          />
          <DocumentRows
            documents={itineraryDocuments}
            emptyMessage="No itinerary PDF has been uploaded."
            isUpdating={isUpdating}
            previewingDocumentId={previewingDocumentId}
            onPreview={openPreview}
            onMove={(index, direction) => reorderCollection(itineraryDocuments, index, direction, ITINERARY_CATEGORY)}
            onReplace={startReplacement}
            onSetPublished={setPublished}
            onDelete={setDeleteDocument}
          />
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-5 p-5">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">Other common documents</h3>
            <p className="mt-1 text-sm text-slate-500">Published PDFs, including travel tips, appear under their own headings in the app.</p>
          </div>
          <DocumentUploadForm
            key={`other-${otherReplacement?.id ?? "new"}`}
            id="gc-other-document-upload"
            categories={OTHER_DOCUMENT_CATEGORIES}
            replaceDocument={otherReplacement}
            isUploading={isUploading}
            onUpload={onUpload}
            onComplete={() => setReplaceDocument(null)}
            onError={setError}
          />

          {visibleOtherGroups.length === 0 ? (
            <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">No other common documents uploaded.</p>
          ) : visibleOtherGroups.map((group) => (
            <section key={group.value} className="space-y-3" aria-labelledby={`gc-document-heading-${group.value}`}>
              <div className="flex items-center justify-between gap-3 border-b border-slate-200 pb-2">
                <h4 id={`gc-document-heading-${group.value}`} className="font-semibold text-slate-800">{group.label}</h4>
                <Badge variant="secondary">{group.documents.length}</Badge>
              </div>
              <DocumentRows
                documents={group.documents}
                emptyMessage={`No ${group.label.toLowerCase()} uploaded.`}
                isUpdating={isUpdating}
                previewingDocumentId={previewingDocumentId}
                onPreview={openPreview}
                onMove={(index, direction) => reorderCollection(group.documents, index, direction, group.value)}
                onReplace={startReplacement}
                onSetPublished={setPublished}
                onDelete={setDeleteDocument}
              />
            </section>
          ))}
        </CardContent>
      </Card>

      <GcDialog
        open={Boolean(preview)}
        title={preview?.document.title ?? "Document preview"}
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

function DocumentUploadForm({
  id,
  categories,
  fixedCategory,
  fixedTitle,
  replaceDocument,
  isUploading,
  onUpload,
  onComplete,
  onError,
}: {
  id: string;
  categories?: { value: GcDocumentCategory; label: string }[];
  fixedCategory?: GcDocumentCategory;
  fixedTitle?: string;
  replaceDocument: GcCommonDocument | null;
  isUploading: boolean;
  onUpload: (upload: CommonDocumentUpload) => Promise<void>;
  onComplete: () => void;
  onError: (message: string | null) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState(replaceDocument?.title ?? fixedTitle ?? "");
  const [category, setCategory] = useState<GcDocumentCategory>(
    fixedCategory ?? replaceDocument?.category ?? categories?.[0]?.value ?? "other",
  );
  const [fileInputKey, setFileInputKey] = useState(0);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);

  const upload = async () => {
    onError(null);
    const normalizedTitle = (fixedTitle ?? title).trim();
    if (!file || !normalizedTitle) {
      onError("Choose a PDF and enter a document title.");
      return;
    }
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      onError("Only PDF common documents are accepted.");
      return;
    }
    if (file.size > 25 * 1024 * 1024) {
      onError("The PDF exceeds the 25 MB dashboard upload limit.");
      return;
    }
    try {
      setUploadProgress(0);
      await onUpload({
        file,
        title: normalizedTitle,
        category: fixedCategory ?? category,
        replace_document_id: replaceDocument?.id,
        onProgress: setUploadProgress,
      });
      setFile(null);
      setFileInputKey((value) => value + 1);
      if (!fixedTitle) setTitle("");
      onComplete();
    } catch (uploadError) {
      onError(gcAppErrorMessage(uploadError, "The common document could not be uploaded."));
    } finally {
      setUploadProgress(null);
    }
  };

  return (
    <div id={id} className="scroll-mt-24 space-y-4 rounded-xl border border-slate-200 bg-slate-50/60 p-4">
      <div>
        <h4 className="font-semibold text-slate-900">{replaceDocument ? `Upload a new version of ${replaceDocument.title}` : fixedTitle ? `Upload ${fixedTitle} PDF` : "Upload common document"}</h4>
        <p className="mt-1 text-xs text-slate-500">The file remains a draft until you publish it.</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {fixedTitle ? (
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-slate-700">Document title</span>
            <span className="flex h-9 items-center rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-800">{fixedTitle}</span>
          </div>
        ) : (
          <Input label="Document title" value={title} onChange={(event) => setTitle(event.target.value)} required />
        )}
        {fixedCategory ? (
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-slate-700">Category</span>
            <span className="flex h-9 items-center rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-800">Itinerary PDF</span>
          </div>
        ) : (
          <GcSelect
            id={`${id}-category`}
            label="Category"
            value={category}
            options={categories ?? []}
            onChange={(nextCategory) => setCategory(nextCategory as GcDocumentCategory)}
          />
        )}
      </div>
      <label className="relative flex min-h-24 cursor-pointer flex-col items-center justify-center overflow-hidden rounded-xl border border-dashed border-slate-300 bg-white px-4 py-5 text-center hover:border-blue-400 hover:bg-blue-50/40 focus-within:ring-2 focus-within:ring-blue-600">
        <Upload className="h-5 w-5 text-slate-400" aria-hidden="true" />
        <span className="mt-2 text-sm font-medium text-slate-700">{file ? file.name : "Choose PDF"}</span>
        <span className="mt-1 text-xs text-slate-500">PDF only, up to 25 MB</span>
        <input
          key={fileInputKey}
          type="file"
          accept="application/pdf,.pdf"
          className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
          onChange={(event) => {
            const nextFile = event.target.files?.[0] ?? null;
            setFile(nextFile);
            if (nextFile && !fixedTitle && !title) setTitle(nextFile.name.replace(/\.pdf$/i, ""));
          }}
        />
      </label>
      {isUploading && uploadProgress !== null ? (
        <div
          className="space-y-2 rounded-xl border border-blue-100 bg-blue-50/70 p-3"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={uploadProgress}
          aria-label="Document upload progress"
        >
          <div className="flex items-center justify-between gap-3 text-xs font-medium text-blue-900">
            <span>{uploadProgress < 100 ? "Uploading PDF" : "Upload complete — checking and saving PDF"}</span>
            <span>{uploadProgress}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-blue-100">
            <div
              className="h-full rounded-full bg-blue-600 transition-[width] duration-200 ease-out"
              style={{ width: `${uploadProgress}%` }}
            />
          </div>
        </div>
      ) : null}
      <div className="flex justify-end">
        <Button type="button" isLoading={isUploading} onClick={() => void upload()}>
          {isUploading && uploadProgress !== null
            ? uploadProgress < 100 ? `Uploading ${uploadProgress}%` : "Checking PDF"
            : replaceDocument ? "Upload replacement as draft" : "Upload as draft"}
        </Button>
      </div>
    </div>
  );
}

function DocumentRows({
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
                <Badge variant={document.is_published ? "success" : "outline"}>{document.is_published ? "Published" : "Draft"}</Badge>
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

function documentById(id: string) {
  return typeof document === "undefined" ? null : document.getElementById(id);
}
