import type { PassportFinalQualityResult } from "./passport-final.types.ts";
import type { PassportPageSide } from "./passport-camera-guide";
import { PASSPORT_FINAL_THRESHOLDS } from "./passport-final-policy.ts";
import { invalidResult } from "./passport-final-result.ts";
import { analyzePassportFinalPixels } from "./passport-final-analysis.ts";

/** Validate the exact encoded upload; live-frame scores cannot replace this check. */
export async function validatePassportFinalFile(
  file: File,
  pageSide: PassportPageSide,
): Promise<PassportFinalQualityResult> {
  const decoded = await decodeImageFile(file);
  try {
    const scale = Math.min(
      1,
      PASSPORT_FINAL_THRESHOLDS.analysisMaxWidth / decoded.width,
    );
    const width = Math.max(80, Math.round(decoded.width * scale));
    const height = Math.max(50, Math.round(decoded.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) {
      return invalidResult(decoded.width, decoded.height);
    }
    context.drawImage(decoded.image, 0, 0, width, height);
    const pixels = context.getImageData(0, 0, width, height).data;
    return analyzePassportFinalPixels(
      pixels,
      width,
      height,
      pageSide,
      decoded.width,
      decoded.height,
    );
  } finally {
    decoded.close();
  }
}

async function decodeImageFile(file: File): Promise<{
  image: CanvasImageSource;
  width: number;
  height: number;
  close: () => void;
}> {
  if (typeof createImageBitmap === "function") {
    const bitmap = await createImageBitmap(file);
    return {
      image: bitmap,
      width: bitmap.width,
      height: bitmap.height,
      close: () => bitmap.close(),
    };
  }

  const objectUrl = URL.createObjectURL(file);
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const element = new window.Image();
      element.onload = () => resolve(element);
      element.onerror = () => reject(
        new Error("The captured passport image could not be decoded."),
      );
      element.src = objectUrl;
    });
    return {
      image,
      width: image.naturalWidth,
      height: image.naturalHeight,
      close: () => URL.revokeObjectURL(objectUrl),
    };
  } catch (error) {
    URL.revokeObjectURL(objectUrl);
    throw error;
  }
}

export { analyzePassportFinalPixels } from "./passport-final-analysis.ts";
export type { PassportFinalQualityReason, PassportRegionQuality, PassportFinalQualityMetrics, PassportFinalQualityResult } from "./passport-final.types.ts";
