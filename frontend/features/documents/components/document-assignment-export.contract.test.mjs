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
const streamedDownload = read("../../../lib/api/streamed-download.ts");

test("every document assignment view exports its active Excel filter", () => {
  assert.match(controls, /Export \{activeFilterLabel\} Excel/);
  assert.match(controls, /\["not_sent", "Not sent"\]/);
  assert.match(controls, /reviewCounts\[reviewFilter\] === 0/);
  assert.match(workspace, /filter: reviewFilter/);
  assert.match(workspace, /search: reviewSearchQuery/);
  assert.match(hooks, /useExportDocumentAssignments/);
});

test("document assignment export streams the real server-generated xlsx with a bounded fallback", () => {
  assert.match(endpoints, /reviewExport:[\s\S]*export\.xlsx/);
  assert.match(api, /downloadStreamedResponse/);
  assert.match(api, /documentAssignmentFilename/);
  assert.doesNotMatch(api, /responseType: "blob"/);
  assert.doesNotMatch(api, /timeout: 0/);
  assert.match(streamedDownload, /adapter: "fetch"/);
  assert.match(streamedDownload, /responseType: "stream"/);
  assert.match(streamedDownload, /MAX_BOUNDED_DOWNLOAD_FALLBACK_BYTES = 32 \* 1024 \* 1024/);
  assert.match(streamedDownload, /bytesWritten > maxBytes/);
  assert.match(streamedDownload, /DOWNLOAD_HARD_TIMEOUT_MS/);
  assert.match(streamedDownload, /DOWNLOAD_IDLE_TIMEOUT_MS/);
});
