import type { DraftPayload } from "../api/returning-draft.api";

/** Three-way merge: asynchronous extraction must not overwrite a typed edit. */
export function reconcileDraft(base: DraftPayload, local: DraftPayload, remote: DraftPayload): DraftPayload {
  const merged: DraftPayload = { passport_fields: {}, current_details: {}, custom_answers: {}, custom_detail_answers: {} };
  for (const section of Object.keys(merged) as Array<keyof DraftPayload>) {
    for (const key of new Set([...Object.keys(base[section]), ...Object.keys(local[section]), ...Object.keys(remote[section])])) {
      const before = base[section][key]; const mine = local[section][key]; const theirs = remote[section][key];
      if (mine !== before && theirs !== before && mine !== theirs) throw new Error("This draft was changed in another window. Reopen it to review the latest details before continuing.");
      const value = mine === before ? theirs : mine;
      if (value !== undefined) merged[section][key] = value;
    }
  }
  return merged;
}
