import { readFileSync } from "node:fs";

export const passportListSource = [
  "passport-list.tsx", "use-passport-list.ts", "passport-list-overview.tsx",
  "passport-list-filters.tsx", "passport-list-export-controls.tsx",
  "passport-list-table.tsx", "passport-group-list-card.tsx",
].map((name) => readFileSync(new URL(`./${name}`, import.meta.url), "utf8")).join("\n");
