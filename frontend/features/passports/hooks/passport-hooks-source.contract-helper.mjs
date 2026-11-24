import { readFileSync } from "node:fs";

export const passportHooksSource = [
  "use-passports.ts", "use-passport-queries.ts", "use-passport-export-mutations.ts",
  "use-passport-import-mutations.ts", "use-passport-bulk-mutations.ts",
  "use-passport-review-mutations.ts",
].map((name) => readFileSync(new URL(`./${name}`, import.meta.url), "utf8")).join("\n");

export const uploadLinkHooksSource = [
  "use-upload-links.ts", "upload-link-query-keys.ts", "use-upload-link-queries.ts",
  "use-upload-link-mutations.ts", "use-upload-link-roster-mutations.ts",
].map((name) => readFileSync(new URL(`./${name}`, import.meta.url), "utf8")).join("\n");
