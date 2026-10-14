import type { ReturningDraft } from "../api/returning-draft.api";
import type { ReturningHistory } from "../types";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { missingDraftDocuments, replacementBackMissing } from "./draft-document-requirements";

export function savedPassportNeedsReplacement(history: ReturningHistory, draft?: ReturningDraft): boolean {
  return ["cannot_assess", "replacement_required"].includes(history.suitability.outcome) && !draft?.documents.some((item) => item.side === "front" && item.state === "ready");
}

export function draftReviewReadiness(history: ReturningHistory, draft: ReturningDraft | undefined, pending: boolean, confirmed: boolean, group?: UploadLinkResponse) {
  const extracting = draft?.extraction_status === "pending" || draft?.extraction_status === "running";
  const uploaded = new Set(draft?.documents.filter((item) => item.state === "ready").map((item) => item.side));
  const frontChanged = uploaded.has("front"); const backChanged = uploaded.has("back");
  const contact = draft?.verified_phone ?? history.contact_phone;
  const needsContact = history.group_requirements.require_contact_phone && !contact;
  const missing = missingDraftDocuments(history, draft);
  const needsReplacement = savedPassportNeedsReplacement(history, draft);
  const needsBack = replacementBackMissing(group, draft, uploaded);
  const blocked = [draft?.status !== "active", !confirmed, extracting, draft?.extraction_status === "failed", pending, needsContact, missing.length > 0, needsReplacement, needsBack];
  return { extracting, frontChanged, backChanged, contact, needsContact, needsReplacement, needsBack, canSubmit: !blocked.some(Boolean) };
}
