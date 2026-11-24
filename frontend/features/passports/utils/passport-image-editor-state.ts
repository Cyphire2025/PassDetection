import type { PassportImageCropRect, PassportImageLibraryItem } from "../api/passports.api";

export const FULL_IMAGE_CROP: PassportImageCropRect = {
  x: 0,
  y: 0,
  width: 1,
  height: 1,
  rotation_degrees: 0,
};

export function keyboardDelta(key: string, step: number) {
  if (key === "ArrowLeft") return { x: -step, y: 0 };
  if (key === "ArrowRight") return { x: step, y: 0 };
  if (key === "ArrowUp") return { x: 0, y: -step };
  if (key === "ArrowDown") return { x: 0, y: step };
  return null;
}

export function clampSharpness(value: number) {
  if (!Number.isFinite(value)) return 1;
  return Math.min(3, Math.max(1, Math.round(value * 20) / 20));
}

export function mergeImageLibraryItems(
  serverItems: PassportImageLibraryItem[],
  currentItems: PassportImageLibraryItem[],
) {
  const serverIds = new Set(serverItems.map((item) => item.id));
  return [
    ...serverItems,
    ...currentItems.filter((item) => !serverIds.has(item.id)),
  ];
}

export function readEditError(error: unknown, fallback: string) {
  if (
    typeof error === "object"
    && error !== null
  ) {
    if ("response" in error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } })
        .response?.data?.detail;
      if (typeof detail === "string" && detail.trim()) return detail;
    }
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return error instanceof Error && error.message ? error.message : fallback;
}
