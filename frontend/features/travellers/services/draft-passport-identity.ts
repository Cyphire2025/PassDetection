import type { ReturningDraft } from "../api/draft.types";
import type { ReturningHistory } from "../types";

const identity = (value: string) => value.normalize("NFKC").toUpperCase().replace(/[^A-Z0-9]/g, "");
/** Mirror the server's punctuation-insensitive number comparison; it remains authoritative. */
export function draftPassportNumberChanged(history: ReturningHistory, draft?: ReturningDraft) {
  if (!draft) return false;
  const original = history.passport?.number ?? history.extracted_fields?.passport_number ?? "";
  return identity(draft.passport_fields.passport_number ?? "") !== identity(original);
}
