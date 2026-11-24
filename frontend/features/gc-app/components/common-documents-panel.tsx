"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, Card, CardContent } from "@/components/ui";
import type { CommonDocumentUpload, GcCommonDocument, GcDocumentCategory } from "../types";
import { gcAppErrorMessage } from "../utils";
import { GcAlert } from "./gc-app-feedback";
import { GcDialog } from "./gc-dialog";
import { DocumentUploadForm } from "./common-document-upload-form";
import { DocumentRows } from "./common-document-rows";

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
  disabled = false,
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
  disabled?: boolean;
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
  const [now, setNow] = useState(() => Date.now());
  const previewRequest = useRef({ mounted: false, generation: 0 });
  useEffect(() => {
    const request = previewRequest.current;
    request.mounted = true;
    return () => { request.mounted = false; request.generation += 1; };
  }, []);
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
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);

  const setPublished = async (documentId: string, published: boolean) => {
    setError(null);
    try {
      await onSetPublished(documentId, published);
    } catch (updateError) {
      setError(gcAppErrorMessage(updateError, "The document was not changed."));
    }
  };

  const openPreview = async (document: GcCommonDocument) => {
    const request = previewRequest.current;
    const generation = ++request.generation;
    setError(null);
    try {
      const blob = await onPreview(document.id);
      if (!request.mounted || generation !== request.generation) return;
      setPreview({ document, url: URL.createObjectURL(blob) });
    } catch (previewError) {
      if (!request.mounted || generation !== request.generation) return;
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
    <fieldset disabled={disabled || isUploading || isUpdating} className="min-w-0 space-y-5" aria-label="Trip documents">
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
            now={now}
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
                now={now}
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
        onClose={() => { previewRequest.current.generation += 1; setPreview(null); }}
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
            <Button type="button" variant="danger" disabled={disabled} isLoading={isUpdating} onClick={() => {
              if (!deleteDocument) return;
              setError(null);
              void onDelete(deleteDocument.id).then(() => setDeleteDocument(null)).catch((deleteError: unknown) => setError(gcAppErrorMessage(deleteError, "The document could not be deleted.")));
            }}>Delete document</Button>
          </>
        )}
      >
        <p className="text-sm text-slate-600">Document history remains auditable. This action does not affect personal passenger documents.</p>
      </GcDialog>
    </fieldset>
  );
}

function documentById(id: string) {
  return typeof document === "undefined" ? null : document.getElementById(id);
}
