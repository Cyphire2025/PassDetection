import { readFileSync } from "node:fs";

const uploadFlowFiles = [
  "./upload-flow.tsx",
  "../services/upload-flow-bootstrap.ts",
  "./upload-flow.types.ts",
  "./upload-flow.constants.ts",
  "./upload-flow-passport-picker.tsx",
  "./upload-flow-fields.tsx",
  "./upload-flow-review.tsx",
  "./upload-flow-shell.tsx",
  "../services/upload-flow-helpers.ts",
  "../services/upload-flow-session.ts",
];

export const uploadFlowSource = uploadFlowFiles
  .map((file) => readFileSync(new URL(file, import.meta.url), "utf8"))
  .join("\n");
