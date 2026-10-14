import type { ReturningDraft } from "@/features/travellers/api/returning-draft.api";
import type { FreshDraftState } from "../hooks/use-fresh-draft";

/** Shared form controls depend on private draft actions, never a publication endpoint. */
export type DraftDocumentInputs = Pick<FreshDraftState, "pending" | "payload" | "collection" | "upload"> & {
  draft?: Pick<ReturningDraft, "documents">;
  api: Pick<FreshDraftState["api"], "document">;
};
export type DraftQualifierInputs = Pick<FreshDraftState, "pending" | "payload" | "collection" | "serialized"> & {
  api: Pick<FreshDraftState["api"], "qualifier">;
};
