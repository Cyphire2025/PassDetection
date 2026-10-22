import type { DraftSide } from "@/features/travellers/api/returning-draft.api";
import { returningApi } from "@/features/travellers/api/returning.api";
import type { ReturningDocument } from "@/features/travellers/types";
import type { DraftDocumentInputs } from "../services/draft-input-contract";
import { DOCUMENT_PREVIEW_LABELS } from "../services/document-preview-order";
import { DocumentProcessingFrame } from "./document-processing-frame";
import { FreshDocumentPreview } from "./fresh-document-preview";
import { SelectedDocumentPreview } from "./selected-document-preview";

type Props = {
  side: DraftSide;
  state: DraftDocumentInputs;
  selected?: File;
  saved?: ReturningDocument;
  status?: string;
};

/** A local replacement takes precedence over the private draft and saved record. */
export function DraftDocumentPreview({ side, state, selected, saved, status }: Props) {
  const document = state.draft?.documents.find((item) => item.side === side);
  const label = DOCUMENT_PREVIEW_LABELS[side];
  const preview = selected
    ? <SelectedDocumentPreview file={selected} label={label} />
    : document
      ? <FreshDocumentPreview key={document.id} id={document.id} label={label} api={state.api} />
      : saved && <FreshDocumentPreview key={saved.id} id={saved.id} label={label} api={returningApi} />;
  return <div className="mt-3"><DocumentProcessingFrame status={status}>{preview}</DocumentProcessingFrame></div>;
}
