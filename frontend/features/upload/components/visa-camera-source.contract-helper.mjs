import { readFileSync } from "node:fs";

export const visaCameraSource = [
  "./visa-selfie-camera.tsx",
  "../hooks/use-visa-photo-capture.ts",
  "../hooks/use-visa-final-face-detection.ts",
  "../hooks/use-visa-camera-shutdown.ts",
  "../hooks/use-visa-camera-state.ts",
  "../hooks/use-visa-detector.ts",
  "../hooks/use-visa-camera-stream.ts",
  "../hooks/use-visa-live-analysis.ts",
  "../hooks/use-visa-camera-controls.ts",
  "../hooks/use-visa-camera.ts",
  "./visa-camera-view.tsx",
  "./visa-camera-footer.tsx",
  "./visa-camera.types.ts",
  "./visa-camera.constants.ts",
  "../services/visa-camera-geometry.ts",
  "../services/visa-camera-final-validation.ts",
  "../services/visa-camera-frame-analysis.ts",
  "../services/visa-camera-image-encoding.ts",
].map((relative) => readFileSync(new URL(relative, import.meta.url), "utf8")).join("\n");
