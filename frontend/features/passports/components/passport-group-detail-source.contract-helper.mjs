import { readFileSync } from "node:fs";

const passportGroupDetailFiles = [
  "./passport-group-detail.tsx",
  "./passport-document-cell.tsx",
  "./passport-document-import-dialog.tsx",
  "./passport-trip-details-dialog.tsx",
  "../utils/passport-document-import.ts",
  "../utils/passport-group-trip.ts",
];

export const passportGroupDetailSource = passportGroupDetailFiles
  .map((file) => readFileSync(new URL(file, import.meta.url), "utf8"))
  .join("\n");
