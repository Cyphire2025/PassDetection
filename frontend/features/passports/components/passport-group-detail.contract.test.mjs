import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("./passport-group-detail.tsx", import.meta.url),
  "utf8",
);
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

test("group confidence displays the same server-computed value used for sorting", () => {
  assert.match(
    source,
    /formatConfidence\(passport\.verification_confidence \?\? null\)/,
  );
  assert.doesNotMatch(source, /getGroupVerificationConfidence/);
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

test("expiry alerts are collapsible through an accessible disclosure control", () => {
  assert.match(source, /const \[isExpiryAlertsExpanded, setIsExpiryAlertsExpanded\] = useState\(true\)/);
  assert.match(source, /aria-expanded=\{isExpiryAlertsExpanded\}/);
  assert.match(source, /aria-controls=\{expiryAlertsRegionId\}/);
  assert.match(source, /id=\{expiryAlertsRegionId\}/);
  assert.match(source, /setIsExpiryAlertsExpanded\(\(current\) => !current\)/);
  assert.match(source, /\{isExpiryAlertsExpanded && \(/);
});

test("selection actions stay hidden until a passport is selected", () => {
  assert.match(
    source,
    /\{selectedPassports\.length > 0 && \([\s\S]*?Export Selected[\s\S]*?Delete Selected[\s\S]*?Clear selection[\s\S]*?\)\}/,
  );
  assert.doesNotMatch(
    source,
    /disabled=\{selectedPassports\.length === 0\}/,
  );
});

test("submission toolbar remains a compact non-wrapping row with horizontal overflow", () => {
  assert.match(
    source,
    /className="flex flex-nowrap items-center gap-2 overflow-x-auto rounded-xl/,
  );
  assert.match(source, /className="shrink-0 whitespace-nowrap"/);
  assert.match(source, /\{viewMode === "docs" \? "Table view" : "DOCS view"\}/);
  assert.doesNotMatch(
    source,
    /className="flex flex-wrap items-center gap-3 rounded-xl/,
  );
});

test("all document-import previews use full-group backend reconciliation", () => {
  assert.match(
    source,
    /passportPreviewMutation\.mutate\(\{[\s\S]*?files,[\s\S]*?Checking documents against the full group/,
  );
  assert.doesNotMatch(source, /buildLocalPassportDocumentPreview/);
  assert.doesNotMatch(source, /containsZip/);
  assert.match(source, /PassportImportPreviewMatrix preview=\{preview\}/);
});
