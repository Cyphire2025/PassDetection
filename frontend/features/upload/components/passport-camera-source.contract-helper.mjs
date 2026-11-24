import { readFileSync } from "node:fs";

// Follow the actual lazy camera entry through its cohesive runtime owners.
export const passportCameraSource = [
  "./smart-camera.tsx",
  "../hooks/use-passport-camera.ts",
  "../hooks/use-passport-camera-session.ts",
  "./passport-camera-view.tsx",
  "./passport-camera-footer.tsx",
  "./passport-camera.types.ts",
  "../services/passport-camera-crop.ts",
  "../services/passport-camera-guidance.ts",
].map(relative => readFileSync(new URL(relative, import.meta.url), "utf8")).join("\n");
