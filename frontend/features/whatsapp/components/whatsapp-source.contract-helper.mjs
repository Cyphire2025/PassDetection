import { readFileSync } from "node:fs";

const sourceFiles = [
  "./whatsapp-workspace.tsx",
  "./whatsapp-recipient-import.tsx",
  "./whatsapp-recipient-dialog.tsx",
  "./whatsapp-recipient-roster-rows.tsx",
  "./whatsapp-create-broadcast-dialog.tsx",
  "./whatsapp-message-preview-dialog.tsx",
];

export const whatsappFeatureSource = sourceFiles
  .map((sourceFile) => readFileSync(new URL(sourceFile, import.meta.url), "utf8"))
  .join("\n");
