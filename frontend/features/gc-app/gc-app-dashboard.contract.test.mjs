import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (relativePath) => readFileSync(new URL(relativePath, import.meta.url), "utf8");

const sidebar = read("../../components/layout/sidebar.tsx");
const routes = read("../../constants/routes.ts");
const proxy = read("../../proxy.ts");
const roleAccess = read("../../lib/utils/role-access.ts");
const routeCapabilities = read("../auth/config/route-capabilities.ts");
const shell = read("./components/gc-app-shell.tsx");
const agencyScope = read("./components/gc-app-agency-scope.tsx");
const api = read("./api/gc-app-admin.api.ts");
const hooks = read("./hooks/use-gc-app-admin.ts");
const managerPage = read("./components/client-manager-accounts-page.tsx");
const managerForm = read("./components/client-manager-form-dialog.tsx");
const managerDetails = read("./components/client-manager-details-dialog.tsx");
const controls = read("./components/app-controls-page.tsx");
const announcements = read("./components/announcements-panel.tsx");
const select = read("./components/gc-select.tsx");
const access = read("./components/group-access-panel.tsx");
const workspace = read("./components/app-control-group-workspace.tsx");
const commonDocuments = read("./components/common-documents-panel.tsx");
const dialog = read("./components/gc-dialog.tsx");
const feedback = read("./components/gc-app-feedback.tsx");
const types = read("./types.ts");
const groupRoute = read("../../app/(dashboard)/gc-app/app-controls/[groupId]/page.tsx");

test("GC App has one top-level sidebar entry and exactly two primary section links", () => {
  assert.equal((sidebar.match(/label: "GC App"/g) ?? []).length, 1);
  assert.doesNotMatch(sidebar, /label: "Client Manager Accounts"/);
  assert.equal((shell.match(/label: "(?:Client Manager Accounts|App Controls)"/g) ?? []).length, 2);
  assert.match(shell, /label: "Client Manager Accounts"/);
  assert.match(shell, /label: "App Controls"/);
});

test("GC App reuses the visible blue Tour Ops workspace header", () => {
  assert.match(shell, /OperationsPageHeader/);
  assert.match(shell, /eyebrow="Global Connect Travels"/);
  assert.doesNotMatch(shell, /from-slate-950|to-blue-950/);
});

test("all GC App routes are centrally registered and protected", () => {
  assert.match(routes, /gcAppRoot: "\/gc-app"/);
  assert.match(routes, /gcAppClientManagerAccounts: "\/gc-app\/client-manager-accounts"/);
  assert.match(routes, /gcAppAppControls: "\/gc-app\/app-controls"/);
  assert.match(routes, /gcAppGroup: \(groupId: string\)/);
  assert.match(proxy, /"\/gc-app"/);
  assert.match(groupRoute, /params: Promise<\{ groupId: string \}>/);
  assert.match(groupRoute, /await params/);
});

test("dashboard visibility uses the GC App management capability", () => {
  assert.match(roleAccess, /GC_APP_MANAGE_CAPABILITY = "gc_app\.manage"/);
  assert.match(roleAccess, /user\.capabilities\.includes\(GC_APP_MANAGE_CAPABILITY\)/);
  assert.match(sidebar, /canAccessApplicationPath\(user, item\.href\)/);
  assert.match(routeCapabilities, /capability === "gc_app\.manage"/);
  assert.match(routeCapabilities, /return canManageGcApp\(user\)/);
  assert.match(shell, /canManageGcApp\(user\)/);
});

test("Client Manager operations use isolated safe account APIs", () => {
  assert.match(api, /\/gc-app\/admin/);
  assert.match(api, /apiClient\.delete\(`\$\{ROOT\}\/client-managers\/\$\{managerId\}`/);
  assert.match(api, /client-managers\/\$\{managerId\}\/revoke-sessions/);
  assert.doesNotMatch(api, /delete_owned_data|operationsApi|API_ENDPOINTS\.admin/);
  assert.match(managerPage, /page_size: GC_APP_DEFAULT_PAGE_SIZE/);
  assert.doesNotMatch(managerPage, /groupcompanion:\/\/activate\?token=/);
  assert.doesNotMatch(managerPage, /Single-use app activation link/);
  assert.doesNotMatch(managerForm, /Force password change|force_password_change/);
  assert.doesNotMatch(managerDetails, /forces a password change|Password change/);
  assert.doesNotMatch(api, /force-password-change/);
  assert.match(api, /force_password_change: false/);
  assert.match(managerDetails, /Type DELETE to confirm/);
  assert.match(managerDetails, /Groups, passengers, and operational history will remain intact/);
});

test("Client Manager session and audit histories use bounded server pagination", () => {
  assert.match(
    api,
    /listClientManagerSessions:[\s\S]{0,600}PageEnvelope<RawClientManagerSession>[\s\S]{0,300}toOffsetParams\(params\)/,
  );
  assert.match(
    api,
    /listClientManagerAudit:[\s\S]{0,600}PageEnvelope<RawAuditEvent>[\s\S]{0,300}toOffsetParams\(params\)/,
  );
  assert.match(hooks, /useClientManagerSessions\([\s\S]{0,300}page = 1[\s\S]{0,500}placeholderData: keepPreviousData/);
  assert.match(hooks, /useClientManagerAudit\([\s\S]{0,300}page = 1[\s\S]{0,500}placeholderData: keepPreviousData/);
  assert.match(managerDetails, /tab === "sessions" \? managerId : null/);
  assert.match(managerDetails, /tab === "audit" \? managerId : null/);
  assert.equal((managerDetails.match(/<GcPagination/g) ?? []).length, 2);
  assert.match(managerDetails, /disabled=\{sessions\.isFetching\}/);
  assert.match(managerDetails, /onPageChange=\{setSessionsPage\}/);
  assert.match(managerDetails, /disabled=\{audit\.isFetching\}/);
  assert.match(managerDetails, /onPageChange=\{setAuditPage\}/);
});

test("group discovery is bounded and GC access mutations are revision safe", () => {
  assert.match(controls, /page_size: 20/);
  assert.match(controls, /page: pickerPage, page_size: 20/);
  assert.match(controls, /onPageChange=\{setPickerPage\}/);
  assert.match(api, /eligible_only: params\.eligible_only \|\| undefined/);
  assert.doesNotMatch(api, /filter\(\(group\) => !params\.eligible_only/);
  assert.match(api, /expected_revision: control\.revision/);
  assert.match(api, /gc_revision: group\.access\?\.revision/);
  assert.match(api, /expected_revision: group\.gc_revision \?\? null/);
  assert.match(hooks, /agencyId, "group-search"/);
  assert.match(api, /apiClient\.put\(\s*`\$\{ROOT\}\/groups\/\$\{control\.id\}`/);
  assert.match(api, /apiClient\.delete\(`\$\{ROOT\}\/groups\/\$\{groupId\}`/);
  assert.match(agencyScope, /Agency workspace/);
  assert.match(api, /agency_id: agencyId \?\? undefined/);
  assert.doesNotMatch(api, /\/upload-links|passports\/upload|API_ENDPOINTS\.uploadLinks/);
  assert.doesNotMatch(hooks, /onMutate/);
  assert.match(access, /does not close, archive, delete, or revoke the passport collection group/);
});

test("My Photos visibility uses a dedicated revision-safe group feature control", () => {
  const fullControlBody = api.slice(
    api.indexOf("function fullControlBody"),
    api.indexOf("function normalizeItinerary"),
  );
  assert.match(types, /my_photos_enabled: boolean/);
  assert.match(api, /my_photos_enabled\?: boolean/);
  assert.match(api, /my_photos_enabled: access\.my_photos_enabled \?\? false/);
  assert.match(api, /setMyPhotosEnabled:[\s\S]{0,500}features\/my-photos/);
  assert.match(api, /setMyPhotosEnabled:[\s\S]{0,500}enabled, expected_revision: control\.revision/);
  assert.doesNotMatch(fullControlBody, /my_photos_enabled/);
  assert.match(hooks, /setMyPhotosEnabled: useMutation/);
  assert.match(hooks, /cancelQueries\(\{ queryKey: controlKey \}\)/);
  assert.match(hooks, /setQueryData<GcAppGroupControl>\(controlKey, updatedControl\)/);
  assert.match(workspace, /actions\.setMyPhotosEnabled\.mutateAsync/);
  assert.match(access, /<AccessSwitch[\s\S]{0,120}label="My Photos"/);
  assert.match(access, /checked=\{control\.my_photos_enabled\}/);
  assert.doesNotMatch(hooks, /onMutate/);
});

test("new groups enable every mobile role while list cards keep role switches in Manage and publish", () => {
  assert.match(api, /passenger_access_enabled: true/);
  assert.match(api, /client_manager_access_enabled: true/);
  assert.match(api, /coordinator_access_enabled: true/);
  assert.doesNotMatch(controls, /<AccessSwitch/);
  assert.match(controls, /can be changed in Manage & publish/);
  assert.match(access, /<AccessSwitch label="Passenger access"/);
  assert.match(access, /<AccessSwitch label="Client Manager access"/);
  assert.match(access, /<AccessSwitch label="Coordinator access"/);
});

test("company/client management remains visible and guarded", () => {
  assert.match(controls, /Saved company\/clients/);
  assert.match(controls, /Type the exact name to confirm/);
  assert.match(controls, /companyRemovalConfirmation\.trim\(\) !== pendingCompanyRemoval\.name/);
  assert.match(api, /client-organizations\/\$\{organizationId\}/);
  assert.match(api, /client-organizations\/search/);
  assert.match(api, /\.\.\.toOffsetParams\(params\)/);
  assert.match(controls, /searchPlaceholder="Find company\/client"/);
  assert.match(controls, /<GcSelect/);
  assert.match(controls, /onPageChange=\{setCompanyPage\}/);
  assert.match(hooks, /removeClientOrganization/);
});

test("group metrics and workspace control loads avoid per-card request fan-out", () => {
  assert.match(api, /active_mobile_users: access\.active_mobile_users \?\? 0/);
  assert.match(api, /synced_device_count: access\.synced_device_count \?\? 0/);
  assert.doesNotMatch(api, /getGroupControl:[\s\S]{0,900}Promise\.all/);
  assert.doesNotMatch(api, /getGroupControl:[\s\S]{0,900}groupPage/);
});

test("publishing remains inside App Controls with fixed itinerary and categorized common documents", () => {
  assert.match(workspace, /type WorkspaceTab = "access" \| "documents" \| "announcements"/);
  assert.doesNotMatch(workspace, /value: "itinerary"/);
  assert.doesNotMatch(workspace, /value: "audit"/);
  assert.doesNotMatch(workspace, /useGcAppGroupAudit|ItineraryEditor|AuditTimeline/);
  assert.match(workspace, /tab !== "access"/);
  assert.doesNotMatch(api, /itineraries\/preview/);
  assert.match(api, /itineraries\/drafts/);
  assert.match(api, /itineraries\/\$\{versionId\}\/publish/);
  assert.match(api, /common-documents/);
  assert.match(api, /common-documents\/\$\{documentId\}\/content/);
  assert.match(api, /responseType: "blob"/);
  assert.match(commonDocuments, /URL\.createObjectURL\(blob\)/);
  assert.match(commonDocuments, /URL\.revokeObjectURL\(preview\.url\)/);
  assert.match(commonDocuments, /Secure dashboard preview/);
  assert.match(api, /announcements/);
  assert.match(api, /const form = new FormData\(\)/);
  assert.match(api, /form\.append\("file", upload\.file\)/);
  assert.match(api, /headers:\s*\{\s*["']Content-Type["']:\s*null\s*\}/);
  assert.match(api, /timeout:\s*120_000/);
  assert.match(commonDocuments, /fixed document appears under the Itinerary heading/);
  assert.match(commonDocuments, /Other common documents/);
  assert.match(commonDocuments, /OTHER_DOCUMENT_CATEGORIES/);
  assert.doesNotMatch(commonDocuments, /value: "itinerary_pdf", label:/);
  assert.doesNotMatch(commonDocuments, /label="Available from"/);
  assert.doesNotMatch(commonDocuments, /label="Available until"/);
  assert.doesNotMatch(api, /form\.append\("available_from"/);
  assert.doesNotMatch(api, /form\.append\("available_until"/);
  assert.match(commonDocuments, /absolute inset-0 h-full w-full cursor-pointer opacity-0/);
  assert.match(hooks, /setQueryData<GcAppGroupContent>/);
  assert.match(hooks, /common_documents: \[uploadedDocument, \.\.\.retainedDocuments\]/);
  assert.match(hooks, /void invalidateContent\(groupId!\)\.catch/);
  assert.doesNotMatch(hooks, /uploadDocument:[\s\S]{0,240}onSuccess: \(\) => invalidateContent/);
  assert.doesNotMatch(api, /headers:\s*\{\s*["']Content-Type["']:\s*["']multipart\/form-data["']/);
});

test("GC App dashboard does not persist sensitive state or expose personal document fields", () => {
  for (const source of [api, hooks, managerPage, controls, workspace, types]) {
    assert.doesNotMatch(source, /localStorage|sessionStorage|indexedDB/);
  }
  assert.doesNotMatch(types, /passport_fields|passport_number|mrz|storage_url|download_url/);
  assert.doesNotMatch(api, /document-distribution|raw_url/);
});

test("new dialogs expose accessible dialog semantics and keyboard handling", () => {
  assert.match(dialog, /role="dialog"/);
  assert.match(dialog, /aria-modal="true"/);
  assert.match(dialog, /event\.key === "Escape"/);
  assert.match(dialog, /event\.key !== "Tab"/);
  assert.match(dialog, /motion-safe:animate-in/);
  assert.match(dialog, /const onCloseRef = useRef\(onClose\)/);
  assert.match(dialog, /\}, \[open\]\);/);
});

test("access switches contain their knobs and expose names and states", () => {
  assert.match(feedback, /role="switch"/);
  assert.match(feedback, /aria-labelledby=\{labelId\}/);
  assert.match(feedback, /aria-describedby=\{statusId\}/);
  assert.match(feedback, /overflow-hidden/);
  assert.match(feedback, /left-0\.5 top-0\.5/);
  assert.match(feedback, /checked \? "Enabled" : "Disabled"/);
});

test("GC App uses the custom accessible dropdown and defers picker-only company loading", () => {
  const featureSources = [managerPage, controls, workspace, commonDocuments, announcements, managerForm, agencyScope];
  for (const source of featureSources) {
    assert.doesNotMatch(source, /<select|<option/);
  }
  assert.match(select, /role="combobox"/);
  assert.match(select, /role="listbox"/);
  assert.match(select, /event\.key === "ArrowDown"/);
  assert.match(select, /event\.key === "Escape"/);
  assert.match(controls, /useClientCompanies\([^;]+pickerOpen\)/s);
  assert.match(hooks, /enabled = true,[\s\S]{0,300}enabled,/);
});
