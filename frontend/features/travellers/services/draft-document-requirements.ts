import type { ReturningDraft, DraftSide } from "../api/returning-draft.api";
import type { ReturningHistory } from "../types";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { configuredPassportPages, getUploadFlowSettings } from "@/features/upload/services/configured-upload";

const DOCUMENT_REQUIREMENTS: Record<string, DraftSide> = { passport_front: "front", passport_back: "back", passport_cover: "cover", passport_back_cover: "back_cover", visa_photo: "photo" };

export function missingDraftDocuments(history: ReturningHistory, draft?: ReturningDraft): string[] {
  const uploaded = new Set(draft?.documents.filter((item) => item.state === "ready").map((item) => item.side));
  return (history.missing_requirements ?? []).filter((key) => key === "fresh_photo" ? !uploaded.has("photo") || !draft?.collection?.visa_photo_source : key === "qualifier_relationship" ? !draft?.collection?.qualifier_selection_token : !uploaded.has(DOCUMENT_REQUIREMENTS[key]));
}

export function requiredUploadSides(history: ReturningHistory): DraftSide[] {
  return (history.missing_requirements ?? []).flatMap((key) => DOCUMENT_REQUIREMENTS[key] ? [DOCUMENT_REQUIREMENTS[key]] : []);
}

export function replacementBackMissing(group: UploadLinkResponse | undefined, draft: ReturningDraft | undefined, uploaded: ReadonlySet<DraftSide>): boolean {
  const pages = group ? configuredPassportPages(getUploadFlowSettings(group).uploadConfig, draft?.collection?.acquisition_mode ?? "file", group.allow_files_from_device) : ["front", "back"];
  return uploaded.has("front") && !uploaded.has("back") && pages.includes("back");
}
