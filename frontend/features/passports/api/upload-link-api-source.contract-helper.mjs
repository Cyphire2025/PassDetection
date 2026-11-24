import { readFileSync } from "node:fs";

export const uploadLinkApiSource = [
  "upload-links.api.ts", "upload-link.types.ts", "upload-link-management.api.ts",
  "upload-link-roster.api.ts", "public-upload-link.api.ts",
].map((name) => readFileSync(new URL(`./${name}`, import.meta.url), "utf8")).join("\n");
