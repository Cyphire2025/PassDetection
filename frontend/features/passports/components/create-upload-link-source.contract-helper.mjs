import { readFileSync } from "node:fs";

export const createUploadLinkPaths = Object.freeze([
  "create-upload-link-modal.tsx",
  "use-create-upload-link-form.ts",
  "create-upload-link-defaults.ts",
  "create-upload-link-details.tsx",
  "create-upload-link-result.tsx",
]);

export const createUploadLinkSource = createUploadLinkPaths
  .map((path) => readFileSync(new URL(path, import.meta.url), "utf8"))
  .join("\n");
