import { type Detection } from "@mediapipe/face_detection";
import { type VisaPhotoFaceGeometry } from "../components/visa-selfie-quality";
import { CAMERA_QUALITY_POLICY } from "./camera-quality-policy";
import { VISA_CAPTURE_MARGIN_RATIO } from "../components/visa-camera.constants";

interface CropBounds {
  left: number;
  top: number;
  width: number;
  height: number;
}

export function faceGeometryFromDetection(
  detection: Detection,
  video: HTMLVideoElement,
  guide: HTMLDivElement,
): VisaPhotoFaceGeometry | null {
  const box = detection.boundingBox;
  const crop = getVisaOutputCrop(video, guide);
  const relativeWidth = (box.width * video.videoWidth) / crop.width;
  const relativeHeight = (box.height * video.videoHeight) / crop.height;
  const centerX = (box.xCenter * video.videoWidth - crop.left) / crop.width;
  const centerY = (box.yCenter * video.videoHeight - crop.top) / crop.height;
  if (![relativeWidth, relativeHeight, centerX, centerY].every(Number.isFinite)) {
    return null;
  }

  const eyePoints = detection.landmarks.slice(0, 2).map((landmark) => ({
    x: (landmark.x * video.videoWidth - crop.left) / crop.width,
    y: (landmark.y * video.videoHeight - crop.top) / crop.height,
  }));
  const validEyes = eyePoints.length === 2
    && eyePoints.every((eye) =>
      Number.isFinite(eye.x)
      && Number.isFinite(eye.y)
      && eye.x >= 0
      && eye.x <= 1
      && eye.y >= 0
      && eye.y <= 1
    );
  const orderedEyes = validEyes
    ? [...eyePoints].sort((first, second) => first.x - second.x)
    : [];

  return {
    centerX,
    centerY,
    width: relativeWidth,
    height: relativeHeight,
    ...(validEyes
      ? { leftEye: orderedEyes[0], rightEye: orderedEyes[1] }
      : {}),
  };
}

export function faceGeometryFromFinalDetection(
  detection: Detection,
): VisaPhotoFaceGeometry | null {
  const box = detection.boundingBox;
  const values = [box.xCenter, box.yCenter, box.width, box.height];
  if (!values.every(Number.isFinite)) return null;
  const eyePoints = detection.landmarks.slice(0, 2).map((landmark) => ({
    x: landmark.x,
    y: landmark.y,
  }));
  const validEyes = eyePoints.length === 2
    && eyePoints.every((eye) =>
      Number.isFinite(eye.x)
      && Number.isFinite(eye.y)
      && eye.x >= 0
      && eye.x <= 1
      && eye.y >= 0
      && eye.y <= 1
    );
  const orderedEyes = validEyes
    ? [...eyePoints].sort((first, second) => first.x - second.x)
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

export function getVisibleGuideCrop(video: HTMLVideoElement, guide: HTMLDivElement): CropBounds {
  const videoRect = video.getBoundingClientRect();
  const guideRect = guide.getBoundingClientRect();
  const scale = Math.max(videoRect.width / video.videoWidth, videoRect.height / video.videoHeight);
  const renderedWidth = video.videoWidth * scale;
  const renderedHeight = video.videoHeight * scale;
  const offsetX = (renderedWidth - videoRect.width) / 2;
  const offsetY = (renderedHeight - videoRect.height) / 2;

  const left = Math.max(0, (guideRect.left - videoRect.left + offsetX) / scale);
  const top = Math.max(0, (guideRect.top - videoRect.top + offsetY) / scale);
  const width = Math.min(video.videoWidth - left, guideRect.width / scale);
  const height = Math.min(video.videoHeight - top, guideRect.height / scale);
  return { left, top, width: Math.max(1, width), height: Math.max(1, height) };
}

export function fitCropToAspect(
  crop: CropBounds,
  targetAspectRatio: number,
): CropBounds {
  const currentAspectRatio = crop.width / crop.height;
  if (currentAspectRatio > targetAspectRatio) {
    const width = crop.height * targetAspectRatio;
    return {
      left: crop.left + (crop.width - width) / 2,
      top: crop.top,
      width,
      height: crop.height,
    };
  }
  const height = crop.width / targetAspectRatio;
  return {
    left: crop.left,
    top: crop.top + (crop.height - height) / 2,
    width: crop.width,
    height,
  };
}

export function getVisaOutputCrop(
  video: HTMLVideoElement,
  guide: HTMLDivElement,
): CropBounds {
  return fitCropToAspect(
    getVisibleGuideCrop(video, guide),
    CAMERA_QUALITY_POLICY.visaOutputWidth
    / CAMERA_QUALITY_POLICY.visaOutputHeight,
  );
}

export function getVisaCaptureCrop(
  video: HTMLVideoElement,
  guide: HTMLDivElement,
): CropBounds {
  const crop = getVisaOutputCrop(video, guide);
  const centerX = crop.left + crop.width / 2;
  const centerY = crop.top + crop.height / 2;
  const requestedScale = 1 + VISA_CAPTURE_MARGIN_RATIO * 2;
  const horizontalScaleLimit = (
    2 * Math.min(centerX, video.videoWidth - centerX)
  ) / crop.width;
  const verticalScaleLimit = (
    2 * Math.min(centerY, video.videoHeight - centerY)
  ) / crop.height;
  const scale = Math.max(
    1,
    Math.min(requestedScale, horizontalScaleLimit, verticalScaleLimit),
  );
  const width = crop.width * scale;
  const height = crop.height * scale;

  return {
    left: centerX - width / 2,
    top: centerY - height / 2,
    width,
    height,
  };
}
