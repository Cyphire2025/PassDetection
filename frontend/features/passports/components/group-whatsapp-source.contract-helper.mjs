import { readFileSync } from "node:fs";

export const groupWhatsAppSource = [
  "./group-whatsapp-broadcast-panel.tsx", "./group-whatsapp-dialogs.tsx",
  "./use-group-whatsapp-tracking.ts", "./group-whatsapp-tracking-stats.tsx",
  "./group-whatsapp-tracking-filters.tsx", "./group-whatsapp-comparison-panel.tsx",
  "./group-whatsapp-resolution-dialogs.tsx",
  "./group-whatsapp-replacement-dialog.tsx", "./group-whatsapp-manage-dialog.tsx",
  "./replacement-recipient-choice.tsx", "./group-whatsapp-tracking-table.tsx",
  "./group-whatsapp-match-table.tsx", "./group-whatsapp-match-row.tsx",
  "./group-whatsapp-tracking-presentation.tsx",
  "./group-whatsapp-tracking-model.ts", "../utils/passport-request-id.ts",
].map((name) => readFileSync(new URL(name, import.meta.url), "utf8")).join("\n");
