import type { Detection } from "@mediapipe/face_detection";
import {
  encodeVisaJpegUnderLimit,
  evaluateFinalVisaPhoto,
  type VisaPhotoFaceGeometry,
  type VisaPhotoFinalValidation,
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
const DETECTOR_TIMEOUT_MS = 8_000;
const MIN_SOURCE_WIDTH = 300;
const MIN_SOURCE_HEIGHT = 400;
const FACE_DETECTION_CONFIDENCE = 0.55;
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
  validation: VisaPhotoFinalValidation;
}

let validationTail: Promise<void> = Promise.resolve();

/**
 * Serializes the legacy MediaPipe WASM runtime across file selections. This
 * prevents rapid re-selection (or React effect replay) from running two native
 * detector calls concurrently on browsers where that can corrupt the runtime.
 */
export function verifyUploadedVisaPhoto(
  sourceFile: File,
): Promise<VerifiedVisaPhotoUpload> {
  const validation = validationTail.then(
    () => verifyUploadedVisaPhotoInternal(sourceFile),
    () => verifyUploadedVisaPhotoInternal(sourceFile),
  );
  validationTail = validation.then(
    () => undefined,
    () => undefined,
  );
  return validation;
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
  validation: VisaPhotoFinalValidation,
): string {
  if (validation.faceCount === "no_face") {
    return "No face was found. Choose a clear original studio photo with the full head visible.";
  }
  if (validation.faceCount === "multiple") {
    return "More than one face is visible. Choose a studio photo containing only the applicant.";
  }
  if (validation.facePlacement === "too_far") {
    return "The face is too small. Choose a closer studio portrait with the head and shoulders clearly visible.";
  }
  if (validation.facePlacement === "too_close") {
    return "Part of the head may be cut off. Choose a studio photo with the full head visible.";
  }
  if (validation.facePlacement === "off_center") {
    return "The face is not centred. Choose a properly centred studio portrait.";
  }
  if (validation.facePlacement === "head_tilt") {
    return "The head is tilted beyond the accepted limit. Choose a straight, front-facing studio portrait.";
  }
  if (validation.clarity?.status === "blurry") {
    return "The face is not sharp enough. Choose a clear, high-quality studio photo.";
  }
  if (validation.clarity?.status === "too_dark") {
    return "The face is too dark. Choose an evenly lit studio photo.";
  }
  if (validation.clarity?.status === "too_bright") {
    return "The face is overexposed. Choose an evenly lit studio photo with visible facial detail.";
  }
  if (validation.background && !validation.background.isPlain) {
    return "The background contains a pattern, line, edge, or object. Choose a studio photo with a plain white background.";
  }
  if (validation.background && !validation.background.isWhite) {
    return "The background is not plain white or is strongly coloured. Choose a studio photo with a plain white background.";
  }
  return "This photo did not meet the Visa Photo requirements. Choose a different original studio photo.";
}

export function visaPhotoUploadRejectionReason(
  validation: VisaPhotoFinalValidation,
): VisaPhotoRejectionReason | null {
  if (validation.faceCount === "no_face") return "no_face";
  if (validation.faceCount === "multiple") return "multiple_faces";
  if (validation.facePlacement && validation.facePlacement !== "ready") {
    return validation.facePlacement;
  }
  if (validation.clarity?.status && validation.clarity.status !== "good") {
    return validation.clarity.status;
  }
  if (validation.background && !validation.background.isPlain) {
    return "background_not_plain";
  }
  if (validation.background && !validation.background.isWhite) {
    return "background_not_light_neutral";
  }
  return null;
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
      const detections = await detectVisaPhotoFaces(exactPhoto.image);
      const face = detections.length === 1
        ? faceGeometryFromDetection(detections[0])
        : null;
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
      const validation = evaluateFinalVisaPhoto({
        faceCount: detections.length,
        face,
        pixels,
        width: ANALYSIS_WIDTH,
        height: ANALYSIS_HEIGHT,
      });
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

async function detectVisaPhotoFaces(
  image: HTMLImageElement,
): Promise<Detection[]> {
  let detector: import("@mediapipe/face_detection").FaceDetection | null = null;
  let initialization: Promise<void> | null = null;
  let send: Promise<void> | null = null;
  try {
    const { FaceDetection } = await import("@mediapipe/face_detection");
    detector = new FaceDetection({
      locateFile: (file) => `/mediapipe/face_detection/${file}`,
    });
    detector.setOptions({
      model: "short",
      selfieMode: false,
      minDetectionConfidence: FACE_DETECTION_CONFIDENCE,
    });
    let resolveDetections!: (detections: Detection[]) => void;
    const results = new Promise<Detection[]>((resolve) => {
      resolveDetections = resolve;
    });
    detector.onResults((value) => resolveDetections(value.detections));
    initialization = detector.initialize();
    await withTimeout(
      initialization,
      DETECTOR_TIMEOUT_MS,
      "Automatic Visa Photo checks could not start. Try again or use the live camera.",
    );
    send = detector.send({ image });
    const [detections] = await withTimeout(
      Promise.all([results, send]),
      DETECTOR_TIMEOUT_MS,
      "Automatic Visa Photo checks took too long. Try again or use the live camera.",
    );
    return detections;
  } catch (error) {
    console.error("Uploaded Visa Photo verification failed", error);
    if (
      error instanceof Error
      && error.message.startsWith("Automatic Visa Photo checks")
    ) {
      throw error;
    }
    throw new Error("Automatic Visa Photo checks could not finish safely. Try again or use the live camera.");
  } finally {
    if (detector) {
      const operations = [initialization, send].filter(
        (operation): operation is Promise<void> => operation !== null,
      );
      const safeToClose = (
        await Promise.all(operations.map((operation) => settlesWithin(
          operation,
          1_500,
        )))
      ).every(Boolean);
      if (safeToClose) {
        await withTimeout(
          detector.close(),
          1_500,
          "Visa Photo detector cleanup timed out.",
        ).catch((error) => {
          console.error("Uploaded Visa Photo detector cleanup failed", error);
        });
      } else {
        // Closing legacy MediaPipe while a native send/initialize call is
        // active can fault Safari's WASM runtime. Leave this already-failed
        // instance unreachable instead; the next serialized attempt creates a
        // clean detector.
        console.error("Uploaded Visa Photo detector did not settle safely");
      }
    }
  }
}

function faceGeometryFromDetection(
  detection: Detection,
): VisaPhotoFaceGeometry | null {
  const box = detection.boundingBox;
  if (![box.xCenter, box.yCenter, box.width, box.height].every(Number.isFinite)) {
    return null;
  }
  const eyes = detection.landmarks.slice(0, 2).map((landmark) => ({
    x: landmark.x,
    y: landmark.y,
  }));
  const validEyes = eyes.length === 2 && eyes.every((eye) => (
    Number.isFinite(eye.x)
    && Number.isFinite(eye.y)
    && eye.x >= 0
    && eye.x <= 1
    && eye.y >= 0
    && eye.y <= 1
  ));
  const orderedEyes = validEyes
    ? [...eyes].sort((first, second) => first.x - second.x)
    : [];
  return {
    centerX: box.xCenter,
    centerY: box.yCenter,
    width: box.width,
    height: box.height,
    ...(validEyes
      ? { leftEye: orderedEyes[0], rightEye: orderedEyes[1] }
      : {}),
  };
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

function withTimeout<T>(
  operation: Promise<T>,
  timeoutMs: number,
  message: string,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timeoutId = window.setTimeout(
      () => reject(new Error(message)),
      timeoutMs,
    );
    operation.then(
      (value) => {
        window.clearTimeout(timeoutId);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timeoutId);
        reject(error);
      },
    );
  });
}

function settlesWithin(
  operation: Promise<unknown>,
  timeoutMs: number,
): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const timeoutId = window.setTimeout(() => {
      if (!settled) resolve(false);
    }, timeoutMs);
    operation.then(
      () => {
        settled = true;
        window.clearTimeout(timeoutId);
        resolve(true);
      },
      () => {
        settled = true;
        window.clearTimeout(timeoutId);
        resolve(true);
      },
    );
  });
}
