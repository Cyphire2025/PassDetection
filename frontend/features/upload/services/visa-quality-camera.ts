import type { VisaPhotoClarityStatus, VisaPhotoFallbackCaptureState } from "./visa-quality.types.ts";

export function isVisaPhotoFrameCaptureReady(
  backgroundStatus: "checking" | "white" | "not_white" | "not_plain",
  clarityStatus: "checking" | VisaPhotoClarityStatus,
): boolean {
  return backgroundStatus === "white"
    && clarityStatus === "good";
}

export function isVisaPhotoFallbackCaptureAllowed({
  cameraReady,
  modelUnavailable,
  userAcknowledgedRequirements,
}: VisaPhotoFallbackCaptureState): boolean {
  return cameraReady
    && modelUnavailable
    && userAcknowledgedRequirements;
}

export function buildVisaPhotoCameraConstraints(
  preferRearCamera = true,
): MediaStreamConstraints {
  return {
    video: {
      ...(preferRearCamera ? { facingMode: { ideal: "environment" } } : {}),
      width: { ideal: 1920 },
      height: { ideal: 1440 },
    },
    audio: false,
  };
}

export async function requestVisaPhotoCamera<T>(
  getUserMedia: (constraints: MediaStreamConstraints) => Promise<T>,
): Promise<T> {
  try {
    return await getUserMedia(buildVisaPhotoCameraConstraints(true));
  } catch (error) {
    const errorName = cameraErrorName(error);
    if (errorName === "NotAllowedError" || errorName === "SecurityError") {
      throw error;
    }
    // facingMode is only a preference and is inconsistently implemented by
    // desktop and in-app browsers. A second request without lens selection
    // preserves a usable camera path without exposing a camera selector.
    return getUserMedia(buildVisaPhotoCameraConstraints(false));
  }
}

function cameraErrorName(error: unknown): string | null {
  if (!error || typeof error !== "object" || !("name" in error)) return null;
  const name = (error as { name?: unknown }).name;
  return typeof name === "string" ? name : null;
}
