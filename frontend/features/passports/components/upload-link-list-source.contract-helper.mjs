import { readFileSync } from "node:fs";

export const uploadLinkListPaths = Object.freeze([
  "upload-link-list.tsx",
  "use-upload-link-list.ts",
  "use-upload-link-copy.ts",
  "upload-link-list-header.tsx",
  "upload-link-list-summary.tsx",
  "upload-link-list-sections.tsx",
  "upload-link-list-dialogs.tsx",
  "upload-link-table.tsx",
  "upload-link-actions.tsx",
  "group-delete-retention-dialog.tsx",
  "upload-link-filter.ts",
]);

export const uploadLinkListSource = uploadLinkListPaths
  .map((path) => readFileSync(new URL(path, import.meta.url), "utf8"))
  .join("\n");
