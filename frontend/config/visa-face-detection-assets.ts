// Bump this whenever a vendored model/loader changes so cached browsers receive
// the matching runtime. All assets remain same-origin, including WASM fetches.
export const VISA_FACE_DETECTION_ASSET_VERSION = "0.4.1646425229-csp1";

export function visaFaceDetectionAssetUrl(file: string): string {
  return `/mediapipe/face_detection/${file}?v=${VISA_FACE_DETECTION_ASSET_VERSION}`;
}
