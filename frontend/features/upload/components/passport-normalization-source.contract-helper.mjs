import { readFileSync } from "node:fs";

export const passportNormalizationSource = [
  "passport-perspective-correction.ts", "passport-normalization.types.ts",
  "passport-quad-detection.ts", "passport-line-fitting.ts", "passport-quad-geometry.ts",
  "passport-perspective-warp.ts", "passport-homography.ts",
  "passport-correction-content.ts", "passport-image-encoding.ts", "camera-pixel-math.ts",
].map(name => readFileSync(new URL(`../services/${name}`, import.meta.url), "utf8")).join("\n");
