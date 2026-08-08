import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { passportGroupDetailSource } from "./passport-group-detail-source.contract-helper.mjs";

const source = passportGroupDetailSource;
const api = readFileSync(
  new URL("../api/passports.api.ts", import.meta.url),
  "utf8",
);
const hooks = readFileSync(
  new URL("../hooks/use-passports.ts", import.meta.url),
  "utf8",
);
const endpoints = readFileSync(
  new URL("../../../lib/api/endpoints.ts", import.meta.url),
  "utf8",
);
const constants = readFileSync(
  new URL("../../../constants/index.ts", import.meta.url),
  "utf8",
);
const thumbnailScheduler = readFileSync(
  new URL("../services/document-thumbnail-scheduler.ts", import.meta.url),
  "utf8",
);
const exportDialog = readFileSync(
  new URL("./passport-export-dialog.tsx", import.meta.url),
  "utf8",
);

test("group action menu escapes the clipped workspace header through a body portal", () => {
  assert.match(source, /import \{ createPortal \} from "react-dom"/);
  assert.match(source, /ref=\{actionsMenuPopupRef\}/);
  assert.match(source, /className="fixed z-\[70\] w-64/);
  assert.match(source, /document\.body/);
  assert.match(
    source,
    /!actionsMenuRef\.current\?\.contains\(target\)[\s\S]*?!actionsMenuPopupRef\.current\?\.contains\(target\)/,
  );
});

test("group confidence displays the same server-computed value used for sorting", () => {
  assert.match(
    source,
    /formatConfidence\(passport\.verification_confidence \?\? null\)/,
  );
  assert.doesNotMatch(source, /getGroupVerificationConfidence/);
});

test("passport image ZIP export is not cut off by the ordinary API timeout", () => {
  assert.match(
    api,
    /exportGroupImages:[\s\S]*?groupImageExport\(groupId\)[\s\S]*?responseType: "blob"[\s\S]*?timeout: 0/,
  );
  assert.match(
    source,
    /mutationErrorMessage\([\s\S]*?exportError,[\s\S]*?exportDialogKind === "passport_images"[\s\S]*?\? "Image download failed"[\s\S]*?: "Excel export failed"/,
  );
  assert.match(
    source,
    /<PassportExportDialog[\s\S]*?isDownloading=\{[\s\S]*?exportDialogKind === "passport_images"[\s\S]*?\? exportImagesMutation\.isPending[\s\S]*?: exportMutation\.isPending/,
  );
});

test("export dialog prevents duplicate checkpoints from rapid repeated clicks", () => {
  assert.match(exportDialog, /const downloadStartedRef = useRef\(false\)/);
  assert.match(
    exportDialog,
    /if \(downloadStartedRef\.current \|\| isDownloading\) return/,
  );
  assert.match(exportDialog, /downloadStartedRef\.current = true/);
  assert.match(source, /requestId: createExportRequestId\(\)/);
  assert.match(source, /crypto\.getRandomValues\(bytes\)/);
});

test("submission controls expose only requested sort, direction, and workflow filters", () => {
  assert.match(source, /Sort by: Name/);
  assert.match(source, /Sort by: Updated/);
  assert.match(source, /Sort by: Verification confidence/);
  assert.match(source, /Ascending/);
  assert.match(source, /Descending/);
  assert.match(source, /All submissions/);
  assert.match(source, /Pending AI Verification/);
  assert.match(source, /AI Approved/);
  assert.match(source, /Needs Review/);
  assert.match(source, /Staff Approved/);
  assert.match(source, /Duplicates/);
  assert.doesNotMatch(source, /All quality/);
  assert.doesNotMatch(source, /Low confidence/);
  assert.doesNotMatch(source, /Missing passport number/);
  assert.doesNotMatch(source, /Pending Extraction<\/option>/);
  assert.match(constants, /submitted: "Pending AI Verification"/);
});

test("sorting, filtering, duplicate clustering, and paging are server-driven", () => {
  assert.match(
    endpoints,
    /groupSubmissionsView:[\s\S]*?submissions-view/,
  );
  assert.match(
    api,
    /submission_filter: PassportGroupSubmissionFilter[\s\S]*?sort_by: PassportGroupSubmissionSort[\s\S]*?sort_order: "asc" \| "desc"[\s\S]*?page: number[\s\S]*?page_size: number/,
  );
  assert.match(
    hooks,
    /useGroupSubmissionsView[\s\S]*?getGroupSubmissionsView\(groupId, params\)/,
  );
  assert.match(source, /cluster_boundaries_preserved/);
  assert.match(source, /Possible duplicate set/);
  assert.match(
    source,
    /Part of a possible duplicate set with \{count\} submissions/,
  );
  assert.doesNotMatch(source, /\{count\} submissions grouped together/);
  assert.match(source, /duplicate_cluster_id/);
  assert.match(source, /Page \{submissionsView\.page\} of/);
  assert.doesNotMatch(
    source,
    /\(data \?\? \[\]\)\.filter\(\(passport\)/,
  );
});

test("search is debounced and expiry alerts do not depend on the visible page", () => {
  assert.match(source, /window\.setTimeout\(\(\) => \{[\s\S]*?setDebouncedSearch/);
  assert.match(source, /submissionsView\?\.expiry_alerts \?\? \[\]/);
  assert.match(source, /submissionsView\?\.group_total \?\? 0/);
  assert.match(source, /passport\.submission_id/);
  assert.match(source, /passport\.passport_number \|\| "Passport number not extracted"/);
  assert.match(source, /passport\.date_of_expiry/);
  assert.doesNotMatch(
    source,
    /data \?\? \[\]\)\.filter\(\(passport\) => getExpiryStatus/,
  );
  assert.doesNotMatch(source, /passport\.client_email \|\| "No email provided"/);
});

test("full-group exports stay enabled when the current page is empty", () => {
  const fullGroupGuards = source.match(
    /\|\| \(submissionsView\?\.group_total \?\? 0\) === 0/g,
  );
  assert.equal(fullGroupGuards?.length, 2);
  assert.doesNotMatch(source, /disabled=\{[^}]*!data\?\.length/);
});

test("expiry alerts are collapsible through an accessible disclosure control", () => {
  assert.match(source, /const \[isExpiryAlertsExpanded, setIsExpiryAlertsExpanded\] = useState\(true\)/);
  assert.match(source, /aria-expanded=\{isExpiryAlertsExpanded\}/);
  assert.match(source, /aria-controls=\{expiryAlertsRegionId\}/);
  assert.match(source, /id=\{expiryAlertsRegionId\}/);
  assert.match(source, /setIsExpiryAlertsExpanded\(\(current\) => !current\)/);
  assert.match(source, /\{isExpiryAlertsExpanded && \(/);
});

test("expiry guidance uses the group Travel/Departure date", () => {
  assert.match(source, /within 6 months of the Travel\/Departure date/);
  assert.match(source, /formatPassportDateForUi\(groupDetails\.travel_date\)/);
  assert.match(source, /label="Travel\/Departure Date"/);
});

test("group rows show imported birth, issue, and expiry dates", () => {
  assert.match(source, />Passport Dates</);
  assert.match(source, /getDashboardPassportDate\(passport, "date_of_birth"\)/);
  assert.match(source, /getDashboardPassportDate\(passport, "date_of_issue"\)/);
  assert.match(source, /getDashboardPassportDate\(passport, "date_of_expiry"\)/);
  assert.match(source, /formatPassportDateForUi/);
});

test("selection actions stay hidden until a passport is selected", () => {
  assert.match(
    source,
    /\{selectedPassports\.length > 0 && \([\s\S]*?Bulk submission actions[\s\S]*?Staff approve all selected[\s\S]*?Export Excel[\s\S]*?Download Passport Images[\s\S]*?Delete selected[\s\S]*?Clear selection[\s\S]*?\)\}/,
  );
  assert.doesNotMatch(
    source,
    /disabled=\{selectedPassports\.length === 0\}/,
  );
});

test("selected passport downloads use the scoped ZIP endpoint without duplicate requests", () => {
  assert.match(
    endpoints,
    /groupSelectedImageExport:[\s\S]*?export-images\/selected/,
  );
  assert.match(
    api,
    /exportSelectedGroupImages:[\s\S]*?groupSelectedImageExport\(groupId\)[\s\S]*?submission_ids: submissionIds[\s\S]*?responseType: "blob"[\s\S]*?timeout: 0[\s\S]*?content-disposition/,
  );
  assert.match(
    hooks,
    /useExportSelectedPassportImages[\s\S]*?exportSelectedGroupImages\(request\)/,
  );
  assert.match(
    source,
    /selectedImageDownloadStartedRef\.current[\s\S]*?exportSelectedImages\.isPending/,
  );
  assert.match(
    source,
    /disabled=\{[\s\S]*?exportSelectedImages\.isPending[\s\S]*?selectedPassports\.length > MAX_SELECTED_IMAGE_DOWNLOAD[\s\S]*?handleSelectedPassportDownload\(\)/,
  );
  assert.match(
    source,
    /mutationErrorMessage\([\s\S]*?downloadError,[\s\S]*?"Selected passport download failed"/,
  );
  assert.match(source, /\{importMessage && \([\s\S]*?role="status"[\s\S]*?aria-live="polite"/);
  const selectedDownloadHandler = source.match(
    /const handleSelectedPassportDownload = \(\) => \{([\s\S]*?)\r?\n  \};\r?\n\r?\n  return \(/,
  )?.[1];
  assert.ok(selectedDownloadHandler);
  assert.doesNotMatch(
    selectedDownloadHandler,
    /setSelectedPassports\(\[\]\)/,
  );
});

test("trip details are collapsed by default behind an accessible disclosure", () => {
  assert.match(
    source,
    /const \[isTripDetailsExpanded, setIsTripDetailsExpanded\] = useState\(false\)/,
  );
  assert.match(source, /aria-expanded=\{isTripDetailsExpanded\}/);
  assert.match(source, /aria-controls=\{tripDetailsRegionId\}/);
  assert.match(source, /setIsTripDetailsExpanded\(\(current\) => !current\)/);
  assert.match(source, /\{isTripDetailsExpanded && \([\s\S]*?id=\{tripDetailsRegionId\}/);
  assert.match(source, /Show details/);
  assert.match(source, /Edit[\s\S]*?\{isTripDetailsExpanded && \(/);
});

test("submission toolbar wraps so the accessible bulk menu is not clipped", () => {
  assert.match(
    source,
    /className="flex flex-wrap items-center gap-2 rounded-xl/,
  );
  assert.match(source, /aria-expanded=\{isBulkActionsMenuOpen\}/);
  assert.match(source, /aria-controls=\{bulkActionsDisclosureId\}/);
  assert.match(source, /bulkActionsButtonRef\.current\?\.focus\(\)/);
  assert.doesNotMatch(
    source,
    /id=\{bulkActionsDisclosureId\}[\s\S]{0,120}?role="menu"/,
  );
  assert.match(source, /\{viewMode === "docs" \? "Table view" : "DOCS view"\}/);
  assert.doesNotMatch(source, /overflow-x-auto rounded-xl/);
});

test("selection presets use the complete filtered and sorted server order", () => {
  assert.match(source, /<option value="all">[\s\S]*?submissionsView\?\.total[\s\S]*?> MAX_BULK_SELECTION[\s\S]*?First 1,500 \(maximum\)[\s\S]*?: "All"/);
  assert.match(source, /<option value="50">First 50<\/option>/);
  assert.match(source, /<option value="100">First 100<\/option>/);
  assert.match(source, /<option value="200">First 200<\/option>/);
  assert.match(source, /<option value="custom">Custom number<\/option>/);
  assert.match(
    source,
    /const orderedIds = submissionsView\?\.ordered_submission_ids \?\? \[\]/,
  );
  assert.match(source, /MAX_BULK_SELECTION = 1500/);
  assert.match(source, /MAX_SELECTED_IMAGE_DOWNLOAD = 500/);
  assert.match(source, /orderedIds\.slice\(0, boundedCount\)/);
  assert.match(source, /const selectedPassportIdSet = useMemo\([\s\S]*?new Set\(selectedPassports\)/);
  assert.doesNotMatch(source, /selectedPassports\.includes\(/);
  assert.match(source, /id="group-submission-custom-selection"[\s\S]*?type="number"[\s\S]*?min=\{1\}/);
});

test("manual selection supports later pages while enforcing the 1,500-record cap", () => {
  assert.match(
    source,
    /for \(const submission of submissionsView\?\.items \?\? \[\]\)[\s\S]*?revisions\.set\(submission\.id, submission\.extraction_revision\)/,
  );
  assert.match(source, /selectedPassports\.length >= MAX_BULK_SELECTION/);
  assert.match(source, /Select at most \$\{MAX_BULK_SELECTION\.toLocaleString\(\)\} submissions at a time\./);
});

test("bulk staff approval is selected-scope, confirmed, and summarized", () => {
  assert.match(
    endpoints,
    /bulkStaffApprove:[\s\S]*?bulk-staff-approve/,
  );
  assert.match(
    api,
    /bulkStaffApprove: async \([\s\S]*?\{ submissions \}/,
  );
  assert.match(
    hooks,
    /useBulkStaffApprovePassportSubmissions\(groupId: string\)[\s\S]*?QUERY_KEYS\.passports\.all[\s\S]*?QUERY_KEYS\.dashboard\.stats/,
  );
  assert.match(source, /title="Staff approve selected submissions\?"/);
  assert.match(source, /bulkStaffApprove\.mutate\(approvalSelections/);
  assert.match(source, /expected_extraction_revision: expectedRevision/);
  assert.match(source, /ordered_selection_snapshot/);
  assert.match(
    source,
    /result\.skipped_submissions[\s\S]*?\.filter\(\(item\) => item\.reason === "not_completed"\)[\s\S]*?\.map/,
  );
  assert.match(source, /Incomplete submissions remain selected/);
  assert.match(source, /item\.reason === "not_completed"/);
  assert.match(source, /item\.reason === "stale"/);
  assert.match(source, /must be refreshed and reviewed again/);
});

test("large selections keep synchronous passport image ZIPs within their safe cap", () => {
  assert.match(
    source,
    /selectedPassports\.length > MAX_SELECTED_IMAGE_DOWNLOAD[\s\S]*?Download Passport Images \(select up to \$\{MAX_SELECTED_IMAGE_DOWNLOAD\}\)/,
  );
  assert.match(source, /const MAX_SELECTED_IMAGE_DOWNLOAD = 500/);
});

test("all document-import previews use full-group backend reconciliation", () => {
  assert.match(
    source,
    /passportPreviewMutation\.mutate\(\{[\s\S]*?files,[\s\S]*?Checking documents against the full group/,
  );
  assert.doesNotMatch(source, /buildLocalPassportDocumentPreview/);
  assert.doesNotMatch(source, /containsZip/);
  assert.match(source, /PassportImportPreviewMatrix preview=\{preview\} files=\{files\}/);
});

test("long client emails wrap inside their own group-row column", () => {
  assert.match(source, /className="min-w-0"[\s\S]*?className="mt-1 break-all text-xs text-slate-500"/);
});

test("DOCS view prefers real saved or local image previews and never shows an Accepted placeholder", () => {
  assert.match(source, /url=\{passport\.passport_photo_url\}/);
  assert.match(source, /url=\{passport\.image_url\}/);
  assert.match(source, /url=\{passport\.passport_back_url\}/);
  assert.match(source, /LocalDocumentThumbnail/);
  assert.match(source, /DeferredDocumentThumbnail/);
  assert.match(source, /new IntersectionObserver/);
  assert.match(source, /rootMargin: "200px 0px"/);
  assert.match(source, /acquireDocumentThumbnailSlot\(controller\.signal\)/);
  assert.match(source, /documentThumbnailUrl\(url\)/);
  assert.match(source, /src=\{loadUrl\}/);
  assert.match(source, /fetchPriority="low"/);
  assert.match(source, /\{file \? \([\s\S]*?<LocalDocumentThumbnail file=\{file\}[\s\S]*?\) : effectiveUrl \? \(/);
  assert.match(source, /URL\.revokeObjectURL\(nextUrl\)/);
  assert.match(source, /object-contain/);
  assert.equal((source.match(/loading="lazy"/g) ?? []).length, 1);
  assert.equal((source.match(/loading="eager"/g) ?? []).length, 1);
  assert.equal((source.match(/decoding="async"/g) ?? []).length, 2);
  assert.doesNotMatch(source, /object-cover/);
  assert.doesNotMatch(source, />\s*Accepted\s*</);
  assert.match(source, /No document/);
  assert.match(source, /<Pencil className="h-3\.5 w-3\.5" \/> Edit/);
});

test("DOCS network previews use bounded same-origin thumbnail scheduling", () => {
  assert.match(thumbnailScheduler, /DOCUMENT_THUMBNAIL_MAX_CONCURRENCY = 6/);
  assert.match(thumbnailScheduler, /activeSlots < DOCUMENT_THUMBNAIL_MAX_CONCURRENCY/);
  assert.match(thumbnailScheduler, /signal\.addEventListener\("abort"/);
  assert.match(thumbnailScheduler, /signal\.removeEventListener\("abort"/);
  assert.match(
    thumbnailScheduler,
    /PASSPORT_IMAGE_PATH = \/\^\\\/api\\\/v1\\\/passports/,
  );
  assert.match(thumbnailScheduler, /\/thumbnail\$\{query\}/);
});

test("completed group pages stop idle polling and rely on focused invalidation", () => {
  assert.match(
    hooks,
    /useGroupSubmissionsView[\s\S]*?isPassportWorkflowPending[\s\S]*?\? 2_000[\s\S]*?: false/,
  );
});
