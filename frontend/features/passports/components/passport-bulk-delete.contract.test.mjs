import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const component = readFileSync(
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

test("bulk delete uses a group-scoped API command and invalidates passport data", () => {
  assert.match(
    endpoints,
    /bulkDelete: \(groupId: string\) => `\/api\/v1\/passports\/groups\/\$\{groupId\}\/bulk-delete`/,
  );
  assert.match(
    api,
    /bulkDelete: async \([\s\S]*?submission_ids: submissionIds/,
  );
  assert.match(
    hooks,
    /useBulkDeletePassportSubmissions\(groupId: string\)[\s\S]*?QUERY_KEYS\.passports\.all[\s\S]*?QUERY_KEYS\.dashboard\.stats/,
  );
});

test("only permanent-delete roles receive the selected-row delete control", () => {
  assert.match(
    component,
    /role === "super_admin" \|\| role === "agency_admin"/,
  );
  assert.match(
    component,
    /canPermanentlyDelete && !includeDeleted/,
  );
  assert.match(
    component,
    /Delete selected \(\{selectedPassports\.length\}\)/,
  );
  assert.match(
    component,
    /\{selectedPassports\.length > 0 && \(/,
  );
  assert.match(
    component,
    /disabled=\{bulkDelete\.isPending\}/,
  );
  assert.match(component, /role="menu"[\s\S]*?aria-label="Bulk submission actions"/);
});

test("bulk delete requires a count-specific destructive confirmation", () => {
  assert.match(component, /title="Delete selected submissions\?"/);
  assert.match(
    component,
    /Permanently delete \$\{selectedPassports\.length\} selected passport submission/,
  );
  assert.match(component, /variant="danger"/);
  assert.match(component, /isLoading=\{bulkDelete\.isPending\}/);
});

test("success clears selection while failures remain visible", () => {
  assert.match(
    component,
    /onSuccess: \(result\) => \{[\s\S]*?setSelectedPassports\(\[\]\)[\s\S]*?tone: "success"/,
  );
  assert.match(
    component,
    /onError: \(deleteError\) => \{[\s\S]*?tone: "error"/,
  );
  assert.match(
    component,
    /mutationErrorMessage\([\s\S]*?typeof error\.message === "string"/,
  );
  assert.match(
    component,
    /result\.storage_cleanup_deferred \? "warning" : "success"/,
  );
  assert.match(
    component,
    /Stored-file cleanup could not finish and was logged for administrator follow-up/,
  );
  assert.match(
    component,
    /role=\{bulkDeleteFeedback\.tone === "error" \? "alert" : "status"\}/,
  );
});
