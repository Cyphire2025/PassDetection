import { reconcileDraft } from "@/features/travellers/services/draft-reconcile";
import { draftFieldValue } from "@/features/travellers/services/draft-field-value";
import type { FreshPayload } from "../api/fresh-draft.api";
export const freshPayload = (view: Omit<FreshPayload, "collection"> & Partial<Pick<FreshPayload, "collection">>): FreshPayload => ({ passport_fields: view.passport_fields, current_details: view.current_details, custom_answers: view.custom_answers, custom_detail_answers: view.custom_detail_answers, collection: view.collection ?? null });
export function reconcileFresh(base: FreshPayload, local: FreshPayload, remote: FreshPayload, preserveLocal = false): FreshPayload {
  const collection = { ...remote.collection };
  for (const key of new Set([...Object.keys(base.collection ?? {}), ...Object.keys(local.collection ?? {})])) {
    const field = key as keyof NonNullable<FreshPayload["collection"]>;
    Object.assign(collection, { [field]: draftFieldValue(base.collection?.[field], local.collection?.[field], remote.collection?.[field], preserveLocal) });
  }
  return { ...reconcileDraft(base, local, remote, preserveLocal), collection: Object.keys(collection).length ? collection as FreshPayload["collection"] : null };
}
export const freshError = (cause: unknown) => cause && typeof cause === "object" && "message" in cause && typeof cause.message === "string" ? cause.message : "This action could not be completed. Please retry.";
