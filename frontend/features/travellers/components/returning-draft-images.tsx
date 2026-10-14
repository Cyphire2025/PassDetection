"use client";

import type { ReturningDraft } from "../api/returning-draft.api";
import type { ReturningDocument } from "../types";
import { TravellerDocument } from "./traveller-document";
import { DOCUMENT_PREVIEW_ORDER as SIDES, DOCUMENT_PREVIEW_LABELS as LABELS, documentSide } from "@/features/upload/services/document-preview-order";

export function ReturningDraftImages({ documents, draft, hidePhoto = false }: {
  documents: ReturningDocument[]; draft: ReturningDraft; hidePhoto?: boolean;
}) {
  const images = SIDES.filter((side) => !hidePhoto || side !== "photo").flatMap((side) => {
    const temporary = draft.documents.find((image) => image.side === side);
    const saved = documents.find((image) => documentSide(image.label) === side);
    return temporary ? [{ id: temporary.id, side, temporary: true, available: true }] : saved ? [{ id: saved.id, side, temporary: false, available: saved.available }] : [];
  });
  return <section className="space-y-4" aria-label="Passport images">
    {images.map((image) => <TravellerDocument key={image.id} id={image.id} draftId={draft.id} label={LABELS[image.side]} temporary={image.temporary} available={image.available} />)}
    {!images.length && <p className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-500">Upload a current passport to add your document preview.</p>}
  </section>;
}
