import type {
  WhiteBackgroundMetrics, VisaPhotoFaceGeometry, VisaPhotoFacePlacementStatus,
  VisaPhotoClarityMetrics, VisaPhotoFaceCountStatus, VisaPhotoFinalValidation,
} from "./visa-quality.types.ts";
import type { CameraValidationOutcome } from "./camera-quality-policy";
import {
  FINAL_BORDERLINE_MIN_FACE_GRADIENT, FINAL_BORDERLINE_MIN_FACE_EDGE_RATIO,
  FINAL_BORDERLINE_MIN_FACE_LUMINANCE, FINAL_BORDERLINE_MAX_FACE_LUMINANCE,
  FINAL_HARD_MIN_BACKGROUND_LUMINANCE, FINAL_HARD_MIN_LIGHT_NEUTRAL_RATIO,
  FINAL_HARD_MAX_STRONG_EDGE_RATIO, FINAL_HARD_MAX_ROUGH_TEXTURE_RATIO,
  FINAL_HARD_MAX_LINE_COVERAGE, FINAL_HARD_MAX_REGIONAL_EDGE_RATIO,
  FINAL_HARD_MAX_REGIONAL_DARK_RATIO, FINAL_HARD_MIN_FAILING_LIGHT_NEUTRAL_ZONES,
  FINAL_HARD_MIN_STRUCTURED_ZONES, FINAL_HARD_MIN_EXTREME_ZONES, LIVE_MIN_LIGHT_NEUTRAL_RATIO,
} from "./visa-quality-policy.ts";
import { evaluateWhiteBackground } from "./visa-quality-background.ts";
import {
  evaluateVisaPhotoFaceCount, evaluateVisaPhotoFacePlacement, definiteFinalFacePlacementFailure,
} from "./visa-quality-face.ts";
import { evaluateVisaPhotoClarity } from "./visa-quality-clarity.ts";

/**
 * Classifies the exact, encoded Visa Photo pixels after a fresh face-detection
 * pass. Only definite capture failures are hard stops; near-threshold quality
 * remains reviewable after an explicit user confirmation.
 */
export function evaluateFinalVisaPhoto({
  faceCount,
  face,
  pixels,
  width,
  height,
}: {
  faceCount: number;
  face: VisaPhotoFaceGeometry | null;
  pixels: Uint8ClampedArray;
  width: number;
  height: number;
}): VisaPhotoFinalValidation {
  const countStatus = evaluateVisaPhotoFaceCount(faceCount);
  if (countStatus === "no_face") {
    return finalValidation(
      "hard_failure",
      "No face was found in the captured photo. Retake with your full head inside the guide.",
      countStatus,
    );
  }
  if (countStatus === "multiple") {
    return finalValidation(
      "hard_failure",
      "More than one face is visible. Retake the photo with only one person in frame.",
      countStatus,
    );
  }
  if (!face) {
    return finalValidation(
      "hard_failure",
      "The captured face position could not be checked. Retake the photo.",
      countStatus,
    );
  }

  const liveFacePlacement = evaluateVisaPhotoFacePlacement(face);
  const hardFacePlacement = definiteFinalFacePlacementFailure(face);
  const facePlacement = hardFacePlacement ?? liveFacePlacement;
  const clarity = evaluateVisaPhotoClarity(pixels, width, height, face);
  const background = evaluateWhiteBackground(
    pixels,
    width,
    height,
    face,
  );
  if (hardFacePlacement) {
    const message = hardFacePlacement === "too_far"
      ? "Your face is too small in the captured photo. Move closer and retake it."
      : hardFacePlacement === "too_close"
        ? "Part of your head may be cut off. Move back slightly and retake the photo."
        : "Your head moved outside the centre of the guide. Retake the photo.";
    return finalValidation(
      "hard_failure",
      message,
      countStatus,
      facePlacement,
      clarity,
      background,
    );
  }
  if (clarity.status === "blurry") {
    return finalValidation(
      "hard_failure",
      "Your face is severely blurred in the captured photo. Hold steady and retake it.",
      countStatus,
      facePlacement,
      clarity,
      background,
    );
  }
  if (clarity.status === "too_dark") {
    return finalValidation(
      "hard_failure",
      "Your face is too dark in the captured photo. Move into brighter, even light and retake it.",
      countStatus,
      facePlacement,
      clarity,
      background,
    );
  }
  if (clarity.status === "too_bright") {
    return finalValidation(
      "hard_failure",
      "Your face is severely overexposed. Move away from harsh light and retake the photo.",
      countStatus,
      facePlacement,
      clarity,
      background,
    );
  }
  if (isDefinitelyInvalidBackground(background)) {
    return finalValidation(
      "hard_failure",
      background.isLightNeutral
        ? "The captured background contains a strong pattern, line, or object. Use a plain light wall and retake the photo."
        : "The captured background is too dark or strongly coloured. Use a white, off-white, or light-neutral wall and retake the photo.",
      countStatus,
      facePlacement,
      clarity,
      background,
    );
  }

  const slightlySoft = (
    clarity.averageGradient < FINAL_BORDERLINE_MIN_FACE_GRADIENT
    && clarity.highGradientRatio < FINAL_BORDERLINE_MIN_FACE_EDGE_RATIO
  );
  const unevenFaceLighting = (
    clarity.averageLuminance < FINAL_BORDERLINE_MIN_FACE_LUMINANCE
    || clarity.averageLuminance > FINAL_BORDERLINE_MAX_FACE_LUMINANCE
  );
  if (
    facePlacement !== "ready"
    || !background.isWhite
    || slightlySoft
    || unevenFaceLighting
  ) {
    const message = facePlacement !== "ready"
      ? facePlacement === "head_tilt"
        ? "Your head is slightly tilted. Confirm the photo is clear and acceptable, or retake it."
        : "Your face moved close to the placement limit. Confirm your full head is visible and centred, or retake the photo."
      : !background.isWhite
        ? "The background is close to the limit for colour or texture. Confirm it is a plain light wall, or retake the photo."
        : slightlySoft
          ? "Your face is slightly soft. Confirm your eyes and facial details are clear, or retake the photo."
          : "The facial lighting is uneven. Confirm all facial details remain clear, or retake the photo.";
    return finalValidation(
      "borderline",
      message,
      countStatus,
      facePlacement,
      clarity,
      background,
    );
  }

  return finalValidation(
    "pass",
    "Visa Photo checks passed.",
    countStatus,
    facePlacement,
    clarity,
    background,
  );
}

/**
 * When the face model is unavailable, validate every pixel signal that remains
 * measurable on the exact JPEG. Face count and geometry stay explicitly
 * unverified, so a non-failing result can only be borderline.
 */
export function evaluateFallbackFinalVisaPhoto({
  pixels,
  width,
  height,
}: {
  pixels: Uint8ClampedArray;
  width: number;
  height: number;
}): VisaPhotoFinalValidation {
  const approximateGuideFace: VisaPhotoFaceGeometry = {
    centerX: 0.5,
    centerY: 0.4,
    width: 0.4,
    height: 0.5,
  };
  const availableChecks = evaluateFinalVisaPhoto({
    faceCount: 1,
    face: approximateGuideFace,
    pixels,
    width,
    height,
  });
  if (availableChecks.outcome === "hard_failure") {
    return {
      ...availableChecks,
      faceCount: "no_face",
      facePlacement: null,
    };
  }
  return finalValidation(
    "borderline",
    "Automatic face count and placement checks were unavailable. The exact photo passed the available lighting, clarity, and background checks; confirm there is one clear, centred face with open eyes.",
    "no_face",
    null,
    availableChecks.clarity,
    availableChecks.background,
  );
}

function isDefinitelyInvalidBackground(
  background: WhiteBackgroundMetrics,
): boolean {
  if (
    !background.isLightNeutral
    && (
      background.averageLuminance < FINAL_HARD_MIN_BACKGROUND_LUMINANCE
      || background.lightNeutralRatio < FINAL_HARD_MIN_LIGHT_NEUTRAL_RATIO
      || (
        background.failingLightNeutralZoneCount
          >= FINAL_HARD_MIN_FAILING_LIGHT_NEUTRAL_ZONES
        && background.lightNeutralRatio < LIVE_MIN_LIGHT_NEUTRAL_RATIO
      )
    )
  ) {
    return true;
  }
  return (
    background.strongEdgeRatio > FINAL_HARD_MAX_STRONG_EDGE_RATIO
    || background.roughTextureRatio > FINAL_HARD_MAX_ROUGH_TEXTURE_RATIO
    || background.maxLineCoverage > FINAL_HARD_MAX_LINE_COVERAGE
    || background.structuredZoneCount >= FINAL_HARD_MIN_STRUCTURED_ZONES
    || background.extremeZoneCount >= FINAL_HARD_MIN_EXTREME_ZONES
    || (
      background.maxRegionalEdgeRatio
        > FINAL_HARD_MAX_REGIONAL_EDGE_RATIO
      && background.maxRegionalDarkRatio
        > FINAL_HARD_MAX_REGIONAL_DARK_RATIO
    )
  );
}

function finalValidation(
  outcome: CameraValidationOutcome,
  message: string,
  faceCount: VisaPhotoFaceCountStatus,
  facePlacement: VisaPhotoFacePlacementStatus | null = null,
  clarity: VisaPhotoClarityMetrics | null = null,
  background: WhiteBackgroundMetrics | null = null,
): VisaPhotoFinalValidation {
  return {
    outcome,
    message,
    faceCount,
    facePlacement,
    clarity,
    background,
  };
}
