import { readFileSync } from "node:fs";

const sourceFiles = [
  "./whatsapp-workspace.tsx",
  "./whatsapp-recipient-import.tsx",
  "./whatsapp-recipient-dialog.tsx",
  "./whatsapp-active-recipient-row.tsx",
  "./whatsapp-recipient-selection.tsx",
  "./whatsapp-recipient-bulk-review.tsx",
  "./whatsapp-recipient-roster-rows.tsx",
  "./whatsapp-create-broadcast-dialog.tsx",
  "./whatsapp-message-preview-dialog.tsx",
  "./whatsapp-message-composer-ui.tsx",
];

export const whatsappFeatureSource = sourceFiles
  .map((sourceFile) => readFileSync(new URL(sourceFile, import.meta.url), "utf8"))
  .join("\n");
