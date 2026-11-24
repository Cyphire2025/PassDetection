import type { VisaJpegEncoding } from "./visa-quality.types.ts";
import { VISA_JPEG_QUALITY_STEPS } from "./visa-quality-policy.ts";

/**
 * Tries progressively smaller JPEG encodings of the same already-sized canvas.
 * The exclusive byte cap is checked against the actual Blob returned by the
 * browser; no second crop, resize, smoothing, or sharpening is performed.
 */
export async function encodeVisaJpegUnderLimit(
  encode: (quality: number) => Promise<Blob>,
  byteLimit: number,
): Promise<VisaJpegEncoding> {
  for (const quality of VISA_JPEG_QUALITY_STEPS) {
    const blob = await encode(quality);
    if (blob.size > 0 && blob.size < byteLimit) {
      return { blob, quality };
    }
  }
  throw new Error("The Visa Photo could not be kept below 2 MB. Retake it in steadier lighting.");
}
