/** Stable quality API; live guidance and final encoded-image acceptance remain separate. */
export { evaluateWhiteBackground } from "../services/visa-quality-background.ts";
export { isInsidePersonGuide } from "../services/visa-quality-background-mask.ts";
export { evaluateLiveVisaPhotoBackground } from "../services/visa-quality-live-background.ts";
export {
  isVisaSelfieFaceLargeEnough, evaluateVisaPhotoFaceCount, evaluateVisaPhotoFacePlacement,
  isVisaPhotoFaceStable,
} from "../services/visa-quality-face.ts";
export { evaluateVisaPhotoClarity } from "../services/visa-quality-clarity.ts";
export { evaluateFinalVisaPhoto, evaluateFallbackFinalVisaPhoto } from "../services/visa-quality-final.ts";
export { encodeVisaJpegUnderLimit } from "../services/visa-quality-encoding.ts";
export {
  isVisaPhotoFrameCaptureReady, isVisaPhotoFallbackCaptureAllowed, buildVisaPhotoCameraConstraints,
  requestVisaPhotoCamera,
} from "../services/visa-quality-camera.ts";
export { VISA_JPEG_QUALITY_STEPS } from "../services/visa-quality-policy.ts";
export type {
  WhiteBackgroundMetrics, VisaPhotoLiveBackgroundStatus, VisaPhotoLiveBackgroundEvaluation,
  NormalizedPoint, VisaPhotoFaceGeometry, VisaPhotoFacePlacementStatus, VisaPhotoClarityStatus,
  VisaPhotoClarityMetrics, VisaPhotoFallbackCaptureState, VisaPhotoFaceCountStatus,
  VisaPhotoFinalValidation, VisaJpegEncoding,
} from "../services/visa-quality.types.ts";
