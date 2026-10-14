import { reconcileDraft } from "@/features/travellers/services/draft-reconcile";
import type { FreshPayload } from "../api/fresh-draft.api";
export const freshPayload = (view: Omit<FreshPayload, "collection"> & Partial<Pick<FreshPayload, "collection">>): FreshPayload => ({ passport_fields: view.passport_fields, current_details: view.current_details, custom_answers: view.custom_answers, custom_detail_answers: view.custom_detail_answers, collection: view.collection ?? null });
export function reconcileFresh(base: FreshPayload, local: FreshPayload, remote: FreshPayload): FreshPayload {
  const collection = { ...remote.collection };
  for (const key of new Set([...Object.keys(base.collection ?? {}), ...Object.keys(local.collection ?? {})])) {
    const field = key as keyof NonNullable<FreshPayload["collection"]>;
    if (local.collection?.[field] !== base.collection?.[field]) {
      if (remote.collection?.[field] !== base.collection?.[field] && remote.collection?.[field] !== local.collection?.[field]) throw new Error("This draft changed in another window. Reload it before continuing.");
      Object.assign(collection, { [field]: local.collection?.[field] });
    }
  }
  return { ...reconcileDraft(base, local, remote), collection: collection as FreshPayload["collection"] };
}
export const freshError = (cause: unknown) => cause && typeof cause === "object" && "message" in cause && typeof cause.message === "string" ? cause.message : "This action could not be completed. Please retry.";
