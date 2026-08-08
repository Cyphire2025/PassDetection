import { readFileSync } from "node:fs";

const WORKSPACE_SOURCE_FILES = [
  "./document-workspace.tsx",
  "./document-workspace-model.ts",
  "./document-workspace-review-controls.tsx",
  "./document-workspace-review-rows.tsx",
  "./document-workspace-upload-status.tsx",
];

export function readDocumentWorkspaceSource() {
  return WORKSPACE_SOURCE_FILES
    .map((relativePath) =>
      readFileSync(new URL(relativePath, import.meta.url), "utf8"),
    )
    .join("\n");
}
