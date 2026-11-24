import { readFileSync } from "node:fs";

const read = relative => readFileSync(new URL(relative, import.meta.url), "utf8");

export const gcAppApiSource = [
  "./api/gc-app-admin.api.ts", "./api/gc-app-wire.types.ts",
  "./api/gc-app-transport.ts", "./api/gc-app-account-mappers.ts",
  "./api/gc-app-content-mappers.ts", "./api/gc-app-directory.api.ts",
  "./api/gc-app-managers.api.ts", "./api/gc-app-groups.api.ts",
  "./api/gc-app-documents.api.ts", "./api/gc-app-itineraries.api.ts",
  "./api/gc-app-announcements.api.ts", "./api/gc-app-audit.api.ts",
].map(read).join("\n");

export const gcAppHooksSource = [
  "./hooks/use-gc-app-admin.ts", "./hooks/gc-app-query-config.ts",
  "./hooks/use-gc-client-directory.ts", "./hooks/use-gc-client-managers.ts",
  "./hooks/use-gc-group-queries.ts", "./hooks/use-gc-group-mutations.ts",
].map(read).join("\n");

export const gcAppControlsSource = [
  "./components/app-controls-page.tsx", "./hooks/use-gc-group-picker.ts",
  "./components/add-gc-app-group-dialog.tsx",
].map(read).join("\n");

export const gcAppManagerDetailsSource = [
  "./components/client-manager-details-dialog.tsx",
  "./hooks/use-client-manager-details.ts", "./components/client-manager-details.types.ts",
].map(read).join("\n");

export const gcAppDocumentsSource = [
  "./components/common-documents-panel.tsx", "./components/common-document-upload-form.tsx",
  "./components/common-document-rows.tsx",
].map(read).join("\n");
