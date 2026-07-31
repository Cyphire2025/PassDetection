import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const list = readFileSync(new URL("./passport-list.tsx", import.meta.url), "utf8");
const detail = readFileSync(
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
const uploadLinkHooks = readFileSync(
  new URL("../hooks/use-upload-links.ts", import.meta.url),
  "utf8",
);
const endpoints = readFileSync(
  new URL("../../../lib/api/endpoints.ts", import.meta.url),
  "utf8",
);
const navigation = readFileSync(
  new URL("../utils/passport-group-navigation.ts", import.meta.url),
  "utf8",
);

test("All Groups uses the additive server-paginated contract", () => {
  assert.match(endpoints, /groupSummaries: "\/api\/v1\/passports\/groups\/summaries"/);
  assert.match(api, /listGroups: async \(\): Promise<PassportGroupSummary\[\]>/);
  assert.match(
    api,
    /listGroupSummaries:[\s\S]*?PassportGroupSummaryPage[\s\S]*?groupSummaries[\s\S]*?\{ params \}/,
  );
  assert.match(
    hooks,
    /usePassportGroupSummaries[\s\S]*?listGroupSummaries\(params\)/,
  );
  assert.match(list, /page_size: GROUPS_PAGE_SIZE/);
  assert.match(list, /group_status: statusFilter/);
  assert.match(list, /review_filter: reviewFilter/);
  assert.match(list, /destination: debouncedDestinationFilter/);
  assert.doesNotMatch(list, /const filteredGroups =/);
  assert.doesNotMatch(list, /\(data \?\? \[\]\)\.filter/);
});

test("All Groups exposes bounded paging while retaining cross-page selection", () => {
  assert.match(list, /const GROUPS_PAGE_SIZE = 50/);
  assert.match(list, /Showing \{\(data\.page - 1\) \* data\.page_size \+ 1\}/);
  assert.match(list, /Page \{data\.page\} of \{Math\.max\(data\.total_pages, 1\)\}/);
  assert.match(list, /\n\s+Previous\n/);
  assert.match(list, /\n\s+Next\n/);
  assert.match(list, /const \[selectedGroups, setSelectedGroups\] = useState<string\[\]>\(\[\]\)/);
  assert.match(list, /groupIds=\{selectedGroups\}/);
  assert.doesNotMatch(
    list,
    /useEffect\(\(\) => \{[\s\S]*?setSelectedGroups\(\[\]\)[\s\S]*?\}, \[page\]\)/,
  );
});

test("direct group metadata uses its authorized single-group query", () => {
  assert.match(
    endpoints,
    /groupSummary: \(groupId: string\)[\s\S]*?groups\/\$\{groupId\}\/summary/,
  );
  assert.match(api, /getGroupSummary:[\s\S]*?groupSummary\(groupId\)/);
  assert.match(
    hooks,
    /usePassportGroupSummary\([\s\S]*?includeArchived = false[\s\S]*?getGroupSummary\(groupId, includeArchived\)/,
  );
  assert.match(
    hooks,
    /usePassportGroupSummary\([\s\S]*?refetchInterval: 30_000/,
  );
  assert.match(
    detail,
    /usePassportGroupSummary\(\s*groupId,\s*!includeDeleted,\s*includeArchived,\s*\)/,
  );
  assert.doesNotMatch(detail, /groups\.find\(\(item\) => item\.group_id === groupId\)/);
});

test("group edits invalidate compatibility, paginated, and direct-summary caches", () => {
  assert.match(
    uploadLinkHooks,
    /queryKey: APP_QUERY_KEYS\.passports\.groups\(\)[\s\S]*?exact: true/,
  );
  assert.match(uploadLinkHooks, /queryKey: \["passports", "group-summaries"\]/);
  assert.match(
    uploadLinkHooks,
    /queryKey: \["passports", "group-summary", groupId\]/,
  );
  assert.match(
    uploadLinkHooks,
    /useCreateUploadLink[\s\S]*?invalidatePassportGroupQueries\(queryClient, response\.id\)/,
  );
  assert.match(
    uploadLinkHooks,
    /useRestoreUploadLink[\s\S]*?invalidatePassportGroupQueries\(queryClient, id\)/,
  );
});

test("archived group results open an explicitly scoped read-only roster", () => {
  assert.match(
    list,
    /group\.group_status === "archived"[\s\S]*?\?include_archived=1/,
  );
  assert.match(
    detail,
    /const includeArchived =[\s\S]*?searchParams\.get\("include_archived"\) === "1"/,
  );
  assert.match(
    detail,
    /const isReadOnlyGroup = includeDeleted \|\| includeArchived/,
  );
  assert.match(detail, /include_archived: includeArchived/);
  assert.match(detail, /canEdit=\{canEditImages && !isReadOnlyGroup\}/);
  assert.match(detail, /canOpen=\{!includeArchived\}/);
  assert.match(
    detail,
    /\{canOpen \? \(\s*<Link[\s\S]*?Open Submission[\s\S]*?\) : \(\s*<Button[\s\S]*?Archived - read only/,
  );
  assert.match(
    detail,
    /\{includeArchived \? \(\s*<Button[\s\S]*?Archived[\s\S]*?\) : \(\s*<Link/,
  );
  assert.doesNotMatch(navigation, /nav_archived/);
});

test("archived access is opt-in on both summary and submissions requests", () => {
  assert.match(api, /include_archived\?: boolean/);
  assert.match(
    api,
    /getGroupSummary:[\s\S]*?includeArchived = false[\s\S]*?include_archived: true/,
  );
  assert.match(
    hooks,
    /groupSummary\(groupId, includeArchived\)[\s\S]*?getGroupSummary\(groupId, includeArchived\)/,
  );
});
