import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (relativePath) =>
  readFileSync(new URL(relativePath, import.meta.url), "utf8");

const workspace = read("./document-workspace.tsx");
const controls = read("./document-workspace-review-controls.tsx");
const api = read("../api/document-distribution.api.ts");
const hooks = read("../hooks/use-document-distribution.ts");
const endpoints = read("../../../lib/api/endpoints.ts");

test("every document assignment view exports its active Excel filter", () => {
  assert.match(controls, /Export \{activeFilterLabel\} Excel/);
  assert.match(controls, /\["not_sent", "Not sent"\]/);
  assert.match(controls, /reviewCounts\[reviewFilter\] === 0/);
  assert.match(workspace, /filter: reviewFilter/);
  assert.match(workspace, /search: reviewSearchQuery/);
  assert.match(hooks, /useExportDocumentAssignments/);
});

test("document assignment export downloads a real server-generated xlsx", () => {
  assert.match(endpoints, /reviewExport:[\s\S]*export\.xlsx/);
  assert.match(api, /responseType: "blob"/);
  assert.match(api, /timeout: 0/);
  assert.match(api, /content-disposition/);
  assert.match(api, /document-assignments-\$\{filter\}\.xlsx/);
  assert.match(api, /URL\.createObjectURL\(blob\)/);
});
