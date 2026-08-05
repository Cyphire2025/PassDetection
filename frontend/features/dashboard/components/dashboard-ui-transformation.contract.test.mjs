import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (name) => readFileSync(new URL(name, import.meta.url), "utf8");

const promptSource = read(
  "../../../../docs/sources/enterprise-dashboard-ui-transformation-prompt.md",
);
const sharedUi = read("../../../components/shared/workspace-ui.tsx");
const intentLink = read("../../../components/shared/intent-prefetch-link.tsx");
const modalUi = read("../../../components/ui/modal.tsx");
const dashboard = read("./dashboard-overview.tsx");
const groupList = read("../../passports/components/passport-list.tsx");
const groupWorkspace = read(
  "../../passports/components/passport-group-detail.tsx",
);
const passengerWorkspace = read("../../passports/components/passport-detail.tsx");
const groupWhatsApp = read(
  "../../passports/components/group-whatsapp-broadcast-panel.tsx",
);
const groupLinks = read("../../passports/components/upload-link-list.tsx");
const whatsappRoute = read("../../whatsapp/components/whatsapp-page.tsx");
const whatsappWorkspace = read(
  "../../whatsapp/components/whatsapp-workspace.tsx",
);
const documentHub = read("../../documents/components/document-hub.tsx");
const documentGroups = read(
  "../../documents/components/document-group-list.tsx",
);
const documentRename = read(
  "../../documents/components/document-rename-page.tsx",
);
const documentWorkspace = read(
  "../../documents/components/document-workspace.tsx",
);
const menu = read("../../menu/components/menu-page.tsx");
const settings = read("../../../app/(dashboard)/settings/page.tsx");
const auditLogs = read("../../../app/(dashboard)/audit-logs/page.tsx");
const analytics = read("../../../app/(dashboard)/analytics/page.tsx");
const roomingGroups = read(
  "../../operations/components/rooming-groups-page.tsx",
);
const roomingWorkspace = read(
  "../../operations/components/rooming-workspace-page.tsx",
);
const operationsUi = read(
  "../../operations/components/operations-workspace-ui.tsx",
);
const routeLoaders = [
  "../../../app/(dashboard)/dashboard/loading.tsx",
  "../../../app/(dashboard)/passports/loading.tsx",
  "../../../app/(dashboard)/passports/[id]/loading.tsx",
  "../../../app/(dashboard)/passports/groups/[groupId]/loading.tsx",
  "../../../app/(dashboard)/passports/groups/[groupId]/whatsapp/loading.tsx",
  "../../../app/(dashboard)/upload-links/loading.tsx",
  "../../../app/(dashboard)/whatsapp/loading.tsx",
  "../../../app/(dashboard)/documents/loading.tsx",
  "../../../app/(dashboard)/documents/rename/loading.tsx",
  "../../../app/(dashboard)/documents/distribution/loading.tsx",
  "../../../app/(dashboard)/documents/distribution/[groupId]/loading.tsx",
  "../../../app/(dashboard)/documents/[groupId]/loading.tsx",
  "../../../app/(dashboard)/settings/loading.tsx",
  "../../../app/(dashboard)/audit-logs/loading.tsx",
  "../../../app/(dashboard)/analytics/loading.tsx",
  "../../../app/(dashboard)/menu/loading.tsx",
].map(read);
const rootLayout = read("../../../app/layout.tsx");
const routeMetadataSources = [
  "../../../app/(dashboard)/dashboard/page.tsx",
  "../../../app/(dashboard)/passports/page.tsx",
  "../../../app/(dashboard)/passports/[id]/page.tsx",
  "../../../app/(dashboard)/passports/groups/[groupId]/page.tsx",
  "../../../app/(dashboard)/passports/groups/[groupId]/whatsapp/page.tsx",
  "../../../app/(dashboard)/upload-links/page.tsx",
  "../../../app/(dashboard)/whatsapp/layout.tsx",
  "../../../app/(dashboard)/documents/page.tsx",
  "../../../app/(dashboard)/documents/rename/page.tsx",
  "../../../app/(dashboard)/documents/distribution/page.tsx",
  "../../../app/(dashboard)/documents/distribution/[groupId]/page.tsx",
  "../../../app/(dashboard)/documents/[groupId]/page.tsx",
  "../../../app/(dashboard)/settings/layout.tsx",
  "../../../app/(dashboard)/audit-logs/layout.tsx",
  "../../../app/(dashboard)/analytics/layout.tsx",
  "../../../app/(dashboard)/menu/page.tsx",
].map(read);

test("the supplied enterprise transformation brief remains stored with the source", () => {
  assert.match(promptSource, /ENTERPRISE-GRADE DASHBOARD UI, UX AND FRONTEND PERFORMANCE/);
  assert.match(promptSource, /The objective is not to alter what the selected feature does\./);
  assert.match(promptSource, /accessibility/i);
  assert.match(promptSource, /responsive/i);
});

test("requested dashboard routes share a compact enterprise workspace system", () => {
  assert.match(sharedUi, /export function WorkspacePageHeader/);
  assert.match(sharedUi, /export function WorkspaceSummaryStrip/);
  assert.match(sharedUi, /export function WorkspaceToolbar/);
  assert.match(sharedUi, /export function WorkspaceEmptyState/);
  assert.match(sharedUi, /export function WorkspaceErrorNotice/);
  assert.match(sharedUi, /#123f73/);

  for (const source of [
    dashboard,
    groupList,
    groupWorkspace,
    passengerWorkspace,
    groupWhatsApp,
    groupLinks,
    whatsappWorkspace,
    documentHub,
    documentGroups,
    documentRename,
    documentWorkspace,
    menu,
    settings,
    auditLogs,
    analytics,
  ]) {
    assert.match(source, /<WorkspacePageHeader/);
  }
});

test("All Groups covers its linked group, passenger, and WhatsApp workflows", () => {
  assert.match(groupList, /IntentPrefetchLink/);
  assert.match(groupList, /ROUTES\.dashboard\.passportGroup\(group\.group_id\)/);
  assert.match(groupWorkspace, /PassportImageCropEditor/);
  assert.match(groupWorkspace, /GroupDocumentDeliveryPanel/);
  assert.match(groupWorkspace, /GroupWhatsAppBroadcastPanel/);
  assert.match(passengerWorkspace, /Extraction revision/);
  assert.match(groupWhatsApp, /communication reconciliation/i);
});

test("large and interaction-heavy routes defer work until it is needed", () => {
  assert.match(intentLink, /router\.prefetch\(href as never\)/);
  assert.match(intentLink, /onMouseEnter/);
  assert.match(groupList, /useDeferredValue/);
  assert.match(groupList, /contentVisibility: "auto"/);
  assert.match(groupWorkspace, /dynamic\(/);
  assert.match(passengerWorkspace, /dynamic\(/);
  assert.match(menu, /dynamic\(/);
  assert.match(whatsappRoute, /dynamic\(/);
  assert.match(whatsappRoute, /import\("\.\/whatsapp-workspace"\)/);
  assert.match(whatsappWorkspace, /useDeferredValue/);
  assert.match(documentGroups, /contentVisibility: "auto"/);
  assert.match(groupList, /loadSelectedGroupsExportDialog/);
  assert.match(groupLinks, /loadCreateUploadLinkModal/);
  assert.match(groupLinks, /onPointerDown=\{\(\) => void loadCreateUploadLinkModal\(\)\}/);
});

test("every requested route branch has a contextual instant loading boundary", () => {
  assert.match(sharedUi, /export function WorkspaceRouteLoading/);
  assert.match(sharedUi, /aria-busy="true"/);
  assert.match(sharedUi, /motion-reduce:animate-none/);
  assert.equal(routeLoaders.length, 16);
  for (const source of routeLoaders) {
    assert.match(source, /<WorkspaceRouteLoading/);
    assert.match(source, /title="Loading /);
  }
});

test("every scoped route has one product-suffixed browser title", () => {
  assert.match(rootLayout, /template: "%s \| Global Connects Dashboard"/);
  assert.equal(routeMetadataSources.length, 16);
  for (const source of routeMetadataSources) {
    assert.match(source, /export const metadata: Metadata/);
    assert.match(source, /title: "[^"]+"/);
    assert.doesNotMatch(source, /title: "[^"]+ \| Global Connects Dashboard"/);
  }
});

test("Menu uses a complete keyboard-operable tab pattern", () => {
  assert.match(menu, /role="tablist"/);
  assert.match(menu, /tabIndex=\{view === "library" \? 0 : -1\}/);
  assert.match(menu, /tabIndex=\{view === "planner" \? 0 : -1\}/);
  assert.match(menu, /event\.key === "ArrowLeft" \|\| event\.key === "ArrowRight"/);
  assert.match(menu, /event\.key === "Home"/);
  assert.match(menu, /event\.key === "End"/);
});

test("operational tables recompose for narrow screens instead of only shrinking", () => {
  for (const source of [dashboard, groupLinks, whatsappWorkspace, auditLogs]) {
    assert.match(source, /md:hidden/);
    assert.match(source, /hidden overflow-x-auto md:block/);
  }
  assert.match(groupLinks, /contentVisibility: "auto"/);
  assert.match(whatsappWorkspace, /contentVisibility: "auto"/);
});

test("dense operational tables expose screen-reader context and scoped columns", () => {
  for (const source of [
    dashboard,
    groupList,
    groupWorkspace,
    groupWhatsApp,
    groupLinks,
    whatsappWorkspace,
    documentRename,
    documentWorkspace,
    auditLogs,
  ]) {
    assert.match(source, /<caption className="sr-only">/);
    assert.match(source, /<th scope="col"/);
  }
});

test("the visual transformation retains each top-level data and mutation contract", () => {
  assert.match(dashboard, /useDashboardStats\(\{ enabled: !isCoordinator \}\)/);
  assert.match(groupList, /usePassportGroups\(\)/);
  assert.match(groupLinks, /useUploadLinks\(\)/);
  assert.match(groupLinks, /useRevokeUploadLink\(\)/);
  assert.match(groupLinks, /useDeleteUploadLink\(\)/);
  assert.match(groupLinks, /useRestoreUploadLink\(\)/);
  assert.match(groupLinks, /useUpdateUploadLink\(\)/);
  assert.match(whatsappWorkspace, /useWhatsAppGroups\(\)/);
  assert.match(documentGroups, /useDocumentGroups\(\)/);
  assert.match(menu, /useMenuWorkspace\(\)/);
  assert.match(settings, /apiClient\s*\.get<PlatformSettings>\(API_ENDPOINTS\.admin\.settings\)/);
  assert.match(settings, /apiClient\s*\.put<PlatformSettings>\(API_ENDPOINTS\.admin\.settings, payload\)/);
  assert.match(settings, /apiClient\s*\.delete<PurgePassportDataResponse>\(API_ENDPOINTS\.admin\.passportData\)/);
  assert.match(auditLogs, /useAuditLogs\(\)/);
  assert.match(analytics, /useAnalyticsSummary\(30\)/);
});

test("shared confirmations and Group Link retention choices expose modal semantics", () => {
  assert.match(modalUi, /role="dialog"/);
  assert.match(modalUi, /aria-modal="true"/);
  assert.match(modalUi, /aria-labelledby=\{titleId\}/);
  assert.match(modalUi, /aria-describedby=\{descriptionId\}/);
  assert.match(groupLinks, /aria-labelledby="delete-archived-group-title"/);
});

test("Rooming now uses the same default navy header as Tour Ops and GC App", () => {
  assert.match(operationsUi, /tone === "navy"[\s\S]*#123f73/);
  assert.doesNotMatch(roomingGroups, /tone="blue"/);
  assert.doesNotMatch(roomingWorkspace, /tone="blue"/);
});
