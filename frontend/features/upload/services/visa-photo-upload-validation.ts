import {
  encodeVisaJpegUnderLimit,
  evaluateWhiteBackground,
  type WhiteBackgroundMetrics,
} from "../components/visa-selfie-quality";
import type { VisaPhotoRejectionReason } from "./public-flow-telemetry";
import { CAMERA_QUALITY_POLICY } from "./camera-quality-policy";

export const VISA_PHOTO_UPLOAD_ACCEPT = [
  ".jpg",
  ".jpeg",
  ".png",
  ".webp",
  ".heic",
  ".heif",
  ".avif",
  "image/jpeg",
  "image/jpg",
  "image/png",
  "image/webp",
  "image/heic",
  "image/heif",
  "image/avif",
].join(",");

export const VISA_PHOTO_UPLOAD_MAX_BYTES = 10 * 1024 * 1024;
export const VISA_PHOTO_UPLOAD_MAX_PIXELS = 24_000_000;

const ANALYSIS_WIDTH = 96;
const ANALYSIS_HEIGHT = 144;
const MIN_SOURCE_WIDTH = 300;
const MIN_SOURCE_HEIGHT = 400;
const ALLOWED_MIME_TYPES = new Set([
  "image/jpeg",
  "image/jpg",
  "image/png",
  "image/webp",
  "image/heic",
  "image/heif",
  "image/avif",
]);
const ALLOWED_FILE_EXTENSION = /\.(?:jpe?g|png|webp|hei[cf]|avif)$/i;

export interface VisaPhotoCropBounds {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface VerifiedVisaPhotoUpload {
  file: File;
  validation: VisaPhotoUploadValidation;
}

export interface VisaPhotoUploadValidation {
  outcome: "pass" | "hard_failure";
  message: string;
  background: WhiteBackgroundMetrics;
}

/**
 * File uploads intentionally use a separate, lightweight policy from live
 * capture. A studio-supplied portrait may already be cropped to many valid
 * head sizes, so uploaded files are gated only on a light, neutral background
 * after the exact outgoing JPEG has been produced. Camera framing, face size,
 * sharpness and pose checks remain exclusive to the live-camera workflow.
 */
export function verifyUploadedVisaPhoto(
  sourceFile: File,
): Promise<VerifiedVisaPhotoUpload> {
  return verifyUploadedVisaPhotoInternal(sourceFile);
}

export function centeredVisaPhotoCrop(
  sourceWidth: number,
  sourceHeight: number,
): VisaPhotoCropBounds {
  const targetRatio = CAMERA_QUALITY_POLICY.visaOutputWidth
    / CAMERA_QUALITY_POLICY.visaOutputHeight;
  const sourceRatio = sourceWidth / sourceHeight;
  if (sourceRatio > targetRatio) {
    const width = sourceHeight * targetRatio;
    return {
      left: (sourceWidth - width) / 2,
      top: 0,
      width,
      height: sourceHeight,
    };
  }
  const height = sourceWidth / targetRatio;
  return {
    left: 0,
    top: (sourceHeight - height) / 2,
    width: sourceWidth,
    height,
  };
}

export function uploadedVisaPhotoFailureMessage(
  validation: VisaPhotoUploadValidation,
): string {
  return validation.message;
}

export function visaPhotoUploadRejectionReason(
  validation: VisaPhotoUploadValidation,
): VisaPhotoRejectionReason | null {
  if (!validation.background.isLightNeutral) {
    return "background_not_light_neutral";
  }
  return null;
}

export function evaluateUploadedVisaPhotoBackground(
  background: WhiteBackgroundMetrics,
): VisaPhotoUploadValidation {
  if (!background.isLightNeutral) {
    return {
      outcome: "hard_failure",
      message: "The background is not white or off-white. Choose a studio photo with a plain white background.",
      background,
    };
  }
  return {
    outcome: "pass",
    message: "White background check passed.",
    background,
  };
}

async function verifyUploadedVisaPhotoInternal(
  sourceFile: File,
): Promise<VerifiedVisaPhotoUpload> {
  validateSourceFile(sourceFile);
  const decodedSource = await decodeVisaPhoto(sourceFile);
  try {
    validateSourceDimensions(
      decodedSource.image.naturalWidth,
      decodedSource.image.naturalHeight,
    );
    const outputCanvas = document.createElement("canvas");
    outputCanvas.width = CAMERA_QUALITY_POLICY.visaOutputWidth;
    outputCanvas.height = CAMERA_QUALITY_POLICY.visaOutputHeight;
    const outputContext = outputCanvas.getContext("2d");
    if (!outputContext) {
      throw new Error("This browser cannot prepare the selected Visa Photo.");
    }
    outputContext.imageSmoothingEnabled = true;
    outputContext.imageSmoothingQuality = "high";
    const crop = centeredVisaPhotoCrop(
      decodedSource.image.naturalWidth,
      decodedSource.image.naturalHeight,
    );
    outputContext.drawImage(
      decodedSource.image,
      crop.left,
      crop.top,
      crop.width,
      crop.height,
      0,
      0,
      CAMERA_QUALITY_POLICY.visaOutputWidth,
      CAMERA_QUALITY_POLICY.visaOutputHeight,
    );

    const { blob } = await encodeVisaJpegUnderLimit(
      (quality) => canvasToJpeg(outputCanvas, quality),
      CAMERA_QUALITY_POLICY.maxVisaOutputBytes,
    );
    const exactPhoto = await decodeVisaPhoto(blob);
    try {
      const analysisCanvas = document.createElement("canvas");
      analysisCanvas.width = ANALYSIS_WIDTH;
      analysisCanvas.height = ANALYSIS_HEIGHT;
      const analysisContext = analysisCanvas.getContext("2d", {
        willReadFrequently: true,
      });
      if (!analysisContext) {
        throw new Error("This browser cannot verify the selected Visa Photo.");
      }
      analysisContext.drawImage(
        exactPhoto.image,
        0,
        0,
        ANALYSIS_WIDTH,
        ANALYSIS_HEIGHT,
      );
      const pixels = analysisContext.getImageData(
        0,
        0,
        ANALYSIS_WIDTH,
        ANALYSIS_HEIGHT,
      ).data;
      // Deliberately omit face geometry so the shared sampler examines only
      // conservative outer wall strips. This prevents hair, shoulders, caps or
      // clothing edges from being misclassified as background defects.
      const background = evaluateWhiteBackground(
        pixels,
        ANALYSIS_WIDTH,
        ANALYSIS_HEIGHT,
      );
      const validation = evaluateUploadedVisaPhotoBackground(background);
      return {
        file: new File([blob], `visa-photo-${Date.now()}.jpg`, {
          type: "image/jpeg",
          lastModified: Date.now(),
        }),
        validation,
      };
    } finally {
      exactPhoto.close();
    }
  } finally {
    decodedSource.close();
  }
}

function validateSourceFile(file: File): void {
  if (!file.size) {
    throw new Error("The selected Visa Photo is empty. Choose another file.");
  }
  if (file.size > VISA_PHOTO_UPLOAD_MAX_BYTES) {
    throw new Error("The selected Visa Photo is larger than 10 MB. Choose a smaller original studio photo.");
  }
  const hasAllowedType = ALLOWED_MIME_TYPES.has(file.type.toLowerCase());
  const hasAllowedExtension = ALLOWED_FILE_EXTENSION.test(file.name);
  if (!hasAllowedType && !hasAllowedExtension) {
    throw new Error("Choose a JPEG, PNG, WebP, HEIC/HEIF, or AVIF studio photo.");
  }
}

function validateSourceDimensions(width: number, height: number): void {
  if (
    !Number.isFinite(width)
    || !Number.isFinite(height)
    || width < MIN_SOURCE_WIDTH
    || height < MIN_SOURCE_HEIGHT
  ) {
    throw new Error("The selected photo resolution is too low. Choose an original studio photo at least 300 × 400 pixels.");
  }
  if (width * height > VISA_PHOTO_UPLOAD_MAX_PIXELS) {
    throw new Error("The selected photo resolution is too large. Export a smaller studio photo and try again.");
  }
  if (width > height) {
    throw new Error("Choose a portrait-oriented studio photo with a plain white background.");
  }
}

function decodeVisaPhoto(blob: Blob): Promise<{
  image: HTMLImageElement;
  close: () => void;
}> {
  const objectUrl = URL.createObjectURL(blob);
  const image = new window.Image();
  image.decoding = "async";
  return new Promise((resolve, reject) => {
    image.onload = () => resolve({
      image,
      close: () => URL.revokeObjectURL(objectUrl),
    });
    image.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error("This browser could not read the selected Visa Photo. Choose a JPEG, PNG, or WebP file."));
    };
    image.src = objectUrl;
  });
}

function canvasToJpeg(
  canvas: HTMLCanvasElement,
  quality: number,
): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => blob
        ? resolve(blob)
        : reject(new Error("This browser could not prepare the selected Visa Photo.")),
      "image/jpeg",
      quality,
    );
  });
}
