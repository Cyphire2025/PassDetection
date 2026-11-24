import type {
  VisaPhotoFaceGeometry, VisaPhotoFacePlacementStatus, VisaPhotoFaceCountStatus,
} from "./visa-quality.types.ts";
import {
  MIN_FACE_WIDTH_RATIO, MIN_FACE_HEIGHT_RATIO, MAX_FACE_WIDTH_RATIO, MAX_FACE_HEIGHT_RATIO,
  MAX_FACE_CENTER_X_OFFSET, MIN_FACE_CENTER_Y, MAX_FACE_CENTER_Y, MAX_EYE_LINE_TILT_DEGREES,
  MAX_STABLE_FACE_CENTER_DELTA, MAX_STABLE_FACE_SIZE_DELTA, FINAL_HARD_MIN_FACE_WIDTH_RATIO,
  FINAL_HARD_MIN_FACE_HEIGHT_RATIO, FINAL_HARD_MAX_FACE_WIDTH_RATIO,
  FINAL_HARD_MAX_FACE_HEIGHT_RATIO, FINAL_HARD_MAX_FACE_CENTER_X_OFFSET,
  FINAL_HARD_MIN_FACE_CENTER_Y, FINAL_HARD_MAX_FACE_CENTER_Y, FINAL_HARD_HEAD_EDGE_MARGIN,
} from "./visa-quality-policy.ts";

export function isVisaSelfieFaceLargeEnough(relativeWidth: number, relativeHeight: number): boolean {
  return relativeWidth >= MIN_FACE_WIDTH_RATIO && relativeHeight >= MIN_FACE_HEIGHT_RATIO;
}

export function evaluateVisaPhotoFaceCount(faceCount: number): VisaPhotoFaceCountStatus {
  if (!Number.isFinite(faceCount) || faceCount <= 0) return "no_face";
  return faceCount === 1 ? "one_face" : "multiple";
}

export function evaluateVisaPhotoFacePlacement(
  face: VisaPhotoFaceGeometry,
): VisaPhotoFacePlacementStatus {
  if (!isVisaSelfieFaceLargeEnough(face.width, face.height)) return "too_far";
  if (face.height > MAX_FACE_HEIGHT_RATIO || face.width > MAX_FACE_WIDTH_RATIO) {
    return "too_close";
  }
  if (
    Math.abs(face.centerX - 0.5) > MAX_FACE_CENTER_X_OFFSET
    || face.centerY < MIN_FACE_CENTER_Y
    || face.centerY > MAX_FACE_CENTER_Y
  ) {
    return "off_center";
  }
  if (face.leftEye && face.rightEye) {
    const eyeLineAngle = Math.atan2(
      Math.abs(face.rightEye.y - face.leftEye.y),
      Math.abs(face.rightEye.x - face.leftEye.x),
    ) * (180 / Math.PI);
    if (eyeLineAngle > MAX_EYE_LINE_TILT_DEGREES) return "head_tilt";
  }
  return "ready";
}

export function isVisaPhotoFaceStable(
  previous: VisaPhotoFaceGeometry | null,
  current: VisaPhotoFaceGeometry,
): boolean {
  if (!previous) return false;
  return (
    Math.abs(previous.centerX - current.centerX)
      <= MAX_STABLE_FACE_CENTER_DELTA
    && Math.abs(previous.centerY - current.centerY)
      <= MAX_STABLE_FACE_CENTER_DELTA
    && Math.abs(previous.width - current.width)
      <= MAX_STABLE_FACE_SIZE_DELTA
    && Math.abs(previous.height - current.height)
      <= MAX_STABLE_FACE_SIZE_DELTA
  );
}

export function definiteFinalFacePlacementFailure(
  face: VisaPhotoFaceGeometry,
): Exclude<VisaPhotoFacePlacementStatus, "head_tilt" | "ready"> | null {
  const top = face.centerY - face.height / 2;
  const bottom = face.centerY + face.height / 2;
  if (
    top < FINAL_HARD_HEAD_EDGE_MARGIN
    || bottom > 1 - FINAL_HARD_HEAD_EDGE_MARGIN
    || face.width > FINAL_HARD_MAX_FACE_WIDTH_RATIO
    || face.height > FINAL_HARD_MAX_FACE_HEIGHT_RATIO
  ) {
    return "too_close";
  }
  if (
    face.width < FINAL_HARD_MIN_FACE_WIDTH_RATIO
    || face.height < FINAL_HARD_MIN_FACE_HEIGHT_RATIO
  ) {
    return "too_far";
  }
  if (
    Math.abs(face.centerX - 0.5)
      > FINAL_HARD_MAX_FACE_CENTER_X_OFFSET
    || face.centerY < FINAL_HARD_MIN_FACE_CENTER_Y
    || face.centerY > FINAL_HARD_MAX_FACE_CENTER_Y
  ) {
    return "off_center";
  }
  return null;
}
