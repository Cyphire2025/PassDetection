import type { DraftSide } from "@/features/travellers/api/returning-draft.api";

export const DOCUMENT_PREVIEW_ORDER: readonly DraftSide[] = ["photo", "front", "back", "cover", "back_cover"];
export const DOCUMENT_PREVIEW_LABELS: Record<DraftSide, string> = {
  photo: "Traveller photo", front: "Passport details page", back: "Passport address page",
  cover: "Front cover", back_cover: "Back cover",
};
export function documentSide(label: string): DraftSide {
  const normalized = label.toLowerCase().replaceAll(" ", "_");
  if (normalized.includes("back_cover")) return "back_cover";
  if (normalized.includes("cover")) return "cover";
  if (normalized.includes("photo")) return "photo";
  if (normalized.includes("back") || normalized.includes("address")) return "back";
  return "front";
}
