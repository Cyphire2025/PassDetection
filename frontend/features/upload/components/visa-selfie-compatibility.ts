/**
 * Compatibility checks used by the live Visa Photo camera.
 *
 * These deliberately preserve the earlier, forgiving capture behavior:
 * one reasonably positioned face and a light neutral wall. The newer strict
 * quality engine remains available for diagnostics and future opt-in use, but
 * furniture-line, texture, head-tilt, and clarity signals do not block capture.
 */

export type VisaPhotoCompatibilityFaceStatus =
  | "no_face"
  | "multiple"
  | "too_far"
  | "too_close"
  | "off_center"
  | "ready";

export interface VisaPhotoCompatibilityFaceGeometry {
  centerX: number;
  centerY: number;
  width: number;
  height: number;
}

export interface PermissiveWhiteBackgroundMetrics {
  isLightNeutral: boolean;
  averageLuminance: number;
  lightNeutralRatio: number;
  darkPixelRatio: number;
  sampleCount: number;
}

const SAMPLE_STEP = 2;
const MIN_FACE_WIDTH_RATIO = 0.31;
const MIN_FACE_HEIGHT_RATIO = 0.38;
const MAX_FACE_WIDTH_RATIO = 0.72;
const MAX_FACE_HEIGHT_RATIO = 0.74;
const MAX_FACE_CENTER_X_OFFSET = 0.11;
const MIN_FACE_CENTER_Y = 0.27;
const MAX_FACE_CENTER_Y = 0.52;

// White and off-white walls often photograph darker and warmer than they look.
// These thresholds reject dark or strongly coloured backgrounds without
// enforcing studio exposure, perfect uniformity, or a clutter-free texture.
const MIN_LIGHT_LUMINANCE = 128;
const MAX_NEUTRAL_CHROMA = 56;
const MIN_LIGHT_NEUTRAL_RATIO = 0.58;
const MIN_AVERAGE_LUMINANCE = 145;
const MAX_DARK_PIXEL_RATIO = 0.22;

export function evaluateCompatibilityVisaPhotoFace(
  faceCount: number,
  face: VisaPhotoCompatibilityFaceGeometry | null,
): VisaPhotoCompatibilityFaceStatus {
  if (!Number.isFinite(faceCount) || faceCount <= 0) return "no_face";
  if (faceCount > 1) return "multiple";
  if (!face) return "no_face";
  if (
    face.width < MIN_FACE_WIDTH_RATIO
    || face.height < MIN_FACE_HEIGHT_RATIO
  ) {
    return "too_far";
  }
  if (
    face.width > MAX_FACE_WIDTH_RATIO
    || face.height > MAX_FACE_HEIGHT_RATIO
  ) {
    return "too_close";
  }
  if (
    Math.abs(face.centerX - 0.5) > MAX_FACE_CENTER_X_OFFSET
    || face.centerY < MIN_FACE_CENTER_Y
    || face.centerY > MAX_FACE_CENTER_Y
  ) {
    return "off_center";
  }
  return "ready";
}

export function evaluatePermissiveWhiteBackground(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
): PermissiveWhiteBackgroundMetrics {
  if (width <= 0 || height <= 0 || pixels.length < width * height * 4) {
    return failedBackgroundMetrics();
  }

  let samples = 0;
  let lightNeutralSamples = 0;
  let darkSamples = 0;
  let luminanceTotal = 0;

  for (let y = 0; y < height; y += SAMPLE_STEP) {
    const normalizedY = (y + 0.5) / height;
    for (let x = 0; x < width; x += SAMPLE_STEP) {
      const normalizedX = (x + 0.5) / width;
      if (!isCompatibilityWallSample(normalizedX, normalizedY)) continue;

      const index = (y * width + x) * 4;
      const red = pixels[index];
      const green = pixels[index + 1];
      const blue = pixels[index + 2];
      const luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue;
      const chroma = Math.max(red, green, blue) - Math.min(red, green, blue);
      const neutralChromaLimit = Math.min(
        MAX_NEUTRAL_CHROMA,
        24 + luminance * 0.15,
      );

      samples += 1;
      luminanceTotal += luminance;
      if (luminance < 100) darkSamples += 1;
      if (
        luminance >= MIN_LIGHT_LUMINANCE
        && chroma <= neutralChromaLimit
      ) {
        lightNeutralSamples += 1;
      }
    }
  }

  if (samples === 0) return failedBackgroundMetrics();

  const averageLuminance = luminanceTotal / samples;
  const lightNeutralRatio = lightNeutralSamples / samples;
  const darkPixelRatio = darkSamples / samples;
  return {
    isLightNeutral: averageLuminance >= MIN_AVERAGE_LUMINANCE
      && lightNeutralRatio >= MIN_LIGHT_NEUTRAL_RATIO
      && darkPixelRatio <= MAX_DARK_PIXEL_RATIO,
    averageLuminance,
    lightNeutralRatio,
    darkPixelRatio,
    sampleCount: samples,
  };
}

/**
 * Match the earlier live camera's narrow wall strips. The centre and lower
 * crop are excluded so hair, ears, clothing, and shoulders cannot cause false
 * background failures.
 */
function isCompatibilityWallSample(x: number, y: number): boolean {
  if (y >= 0.62) return false;
  if (y < 0.40) return x <= 0.06 || x >= 0.94;
  if (y < 0.58) return x <= 0.10 || x >= 0.90;
  return x <= 0.06 || x >= 0.94;
}

function failedBackgroundMetrics(): PermissiveWhiteBackgroundMetrics {
  return {
    isLightNeutral: false,
    averageLuminance: 0,
    lightNeutralRatio: 0,
    darkPixelRatio: 1,
    sampleCount: 0,
  };
}
