import type { FreshDraft, FreshPayload } from "../api/fresh-draft.types";
import type { getUploadFlowSettings } from "./configured-upload";
import { hasMissingRequiredFields, hasValidReviewDates } from "./upload-flow-helpers";

type Settings = ReturnType<typeof getUploadFlowSettings>;
function requiredImageError(settings: Settings, payload: FreshPayload, draft: FreshDraft): string | null {
  const pages = payload.collection?.acquisition_mode === "camera" ? ["front", "back"] : settings.uploadConfig.passport_upload_pages;
  const ready = new Set(draft.documents.filter((document) => document.state === "ready").map((document) => document.side as string));
  if (settings.passportRequired && pages.some((side) => !ready.has(side))) return "Add every requested passport page before submitting.";
  if (settings.selfieRequired && !ready.has("photo")) return "Add your traveller photo before submitting.";
  return null;
}
export function freshDocumentError(settings: Settings, payload: FreshPayload, draft: FreshDraft): string | null {
  const required = requiredImageError(settings, payload, draft);
  if (required) return required;
  if (["pending", "running", "failed"].includes(draft.ecr_status ?? "none")) return "Wait for the passport back-page check to finish. If it failed, upload a clear back-page image.";
  const hasPassport = draft.documents.some((document) => document.side === "front");
  if (hasPassport && draft.extraction_status !== "succeeded") return "Wait for the passport check to finish. If it failed, replace the details page with a clear image.";
  if (hasPassport && hasMissingRequiredFields(payload.passport_fields)) return "Complete the required passport details.";
  if (hasPassport && !hasValidReviewDates(payload.passport_fields)) return "Check your passport dates before submitting.";
  if (!hasPassport && (payload.current_details.client_name ?? "").trim().length < 2) return "Enter your full name.";
  return null;
}
