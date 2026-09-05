import type { FaceDetection as MediaPipeFaceDetection } from "@mediapipe/face_detection";
import { visaFaceDetectionAssetUrl } from "@/config/visa-face-detection-assets";

type FaceDetectionModule = { FaceDetection: typeof MediaPipeFaceDetection };
let modulePromise: Promise<FaceDetectionModule> | null = null;
let initializationTail: Promise<void> = Promise.resolve();

// MediaPipe uses window globals while starting WASM. Camera and file-picker
// instances must not start together when a user quickly switches methods.
export function initializeVisaFaceDetection(
  detector: Pick<MediaPipeFaceDetection, "initialize">,
): Promise<void> {
  const operation = initializationTail.then(() => detector.initialize());
  initializationTail = operation.then(() => undefined, () => undefined);
  return operation;
}

/**
 * Load the pinned, same-origin MediaPipe API whose initializer drains all asset
 * requests on failure. The model and FaceDetection API are unchanged. Sharing
 * the script request avoids duplicate loads when the camera/picker is reopened.
 */
export function loadVisaFaceDetection(): Promise<FaceDetectionModule> {
  if (!modulePromise) {
    modulePromise = new Promise<FaceDetectionModule>((resolve, reject) => {
      const script = document.createElement("script");
      script.src = visaFaceDetectionAssetUrl("face_detection.js");
      script.async = true;
      script.crossOrigin = "anonymous";
      script.onload = () => {
        const runtime = window as typeof window & Partial<FaceDetectionModule>;
        if (typeof runtime.FaceDetection !== "function") {
          script.remove();
          reject(new Error("The face detector could not be loaded."));
          return;
        }
        resolve({ FaceDetection: runtime.FaceDetection });
      };
      script.onerror = () => {
        script.remove();
        reject(new Error("The face detector could not be downloaded."));
      };
      document.head.appendChild(script);
    }).catch((error: unknown) => {
      modulePromise = null;
      throw error;
    });
  }
  return modulePromise;
}
