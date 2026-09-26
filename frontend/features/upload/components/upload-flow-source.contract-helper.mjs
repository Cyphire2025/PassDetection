import { readFileSync } from "node:fs";

const uploadFlowFiles = [
  "./upload-flow.tsx",
  "./upload-review-panels.tsx",
  "../hooks/use-upload-documents.ts",
  "../hooks/use-upload-submission.ts",
  "../hooks/use-upload-operation.ts",
  "../hooks/use-upload-family.ts",
  "../services/review-submission-validation.ts",
  "../services/family-upload-state.ts",
  "../services/upload-operation-state.ts",
  "../services/upload-flow-bootstrap.ts",
  "../services/saved-passport-extraction.ts",
  "./upload-flow.types.ts",
  "./upload-flow.constants.ts",
  "./upload-flow-passport-picker.tsx",
  "./upload-flow-fields.tsx",
  "./upload-flow-review.tsx",
  "./upload-flow-shell.tsx",
  "./upload-flow-status.tsx",
  "../services/upload-flow-helpers.ts",
  "../services/upload-flow-session.ts",
];

export const uploadFlowSource = uploadFlowFiles
  .map((file) => readFileSync(new URL(file, import.meta.url), "utf8"))
  .join("\n");
