import type { DraftPayload } from "../api/returning-draft.api";
import { draftFieldValue } from "./draft-field-value";

/** Three-way merge: asynchronous extraction must not overwrite a typed edit. */
export function reconcileDraft(base: DraftPayload, local: DraftPayload, remote: DraftPayload, preserveLocal = false): DraftPayload {
  const merged: DraftPayload = { passport_fields: {}, current_details: {}, custom_answers: {}, custom_detail_answers: {} };
  for (const section of Object.keys(merged) as Array<keyof DraftPayload>) {
    for (const key of new Set([...Object.keys(base[section]), ...Object.keys(local[section]), ...Object.keys(remote[section])])) {
      const value = draftFieldValue(base[section][key], local[section][key], remote[section][key], preserveLocal);
      if (value !== undefined) merged[section][key] = value;
    }
  }
  return merged;
}
