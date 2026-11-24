import { readFileSync } from "node:fs";

export const passportApiSource = [
  "passports.api.ts", "passport-records.types.ts", "passport-imports.types.ts",
  "passport-exports.types.ts", "passport-images.types.ts", "passport-records.api.ts",
  "passport-images.api.ts", "passport-visa-ai.api.ts", "passport-group-exports.api.ts",
  "passport-imports.api.ts", "passport-selection-exports.api.ts", "passport-export-download.ts",
  "passport-export-transfer.ts",
].map(name => readFileSync(new URL(`./${name}`, import.meta.url), "utf8")).join("\n");
