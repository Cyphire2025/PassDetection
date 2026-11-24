import { readFileSync } from "node:fs";

export const passportExportDialogPaths = Object.freeze([
  "passport-export-dialog.tsx",
  "use-passport-export-dialog.ts",
  "passport-export-fields.tsx",
  "passport-export-history-detail.tsx",
  "passport-export-options.tsx",
  "passport-export-footer.tsx",
]);

export const passportExportDialogSource = passportExportDialogPaths
  .map((path) => readFileSync(new URL(path, import.meta.url), "utf8"))
  .join("\n");
