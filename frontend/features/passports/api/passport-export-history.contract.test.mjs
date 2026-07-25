import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const api = readFileSync(
  new URL("./passports.api.ts", import.meta.url),
  "utf8",
);
const endpoints = readFileSync(
  new URL("../../../lib/api/endpoints.ts", import.meta.url),
  "utf8",
);
const dialog = readFileSync(
  new URL("../components/passport-export-dialog.tsx", import.meta.url),
  "utf8",
);

function methodSource(startMarker, endMarker) {
  const start = api.indexOf(startMarker);
  const end = api.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(start, -1, `${startMarker} is missing`);
  assert.notEqual(end, -1, `${endMarker} is missing`);
  return api.slice(start, end);
}

function assertTwoPhaseBrowserHandshake(source) {
  const header = source.indexOf("x-passport-export-history-id");
  const startDownload = source.indexOf("downloadBlob(");
  const complete = source.indexOf("await confirmStartedGroupExport(");

  assert.ok(header >= 0, "history ID must come from the prepared response");
  assert.ok(startDownload > header, "the Blob must start after the response ID is validated");
  assert.ok(
    complete > startDownload,
    "completion must be posted only after the browser download is initiated",
  );
}

test("Excel and image exports use the prepared-download completion handshake", () => {
  assertTwoPhaseBrowserHandshake(
    methodSource("exportGroup: async", "exportGroupImages: async"),
  );
  assertTwoPhaseBrowserHandshake(
    methodSource("exportGroupImages: async", "importGroup: async"),
  );
  assert.match(
    endpoints,
    /groupExportHistoryComplete:[\s\S]*?export-history\/\$\{historyId\}\/complete/,
  );
  assert.match(
    api,
    /completePreparedGroupExport[\s\S]*?apiClient\.post<PassportGroupExportCompletion>/,
  );
});

test("download history uses completion time and retains deleted-source snapshots", () => {
  assert.match(dialog, /formatDateTime\(item\.completed_at\)/);
  assert.match(dialog, /person\.client_name \|\| "Unnamed upload"/);
  assert.match(dialog, /!person\.record_available[\s\S]*?Original record later deleted/);
  assert.doesNotMatch(dialog, /person\.record_available \? \(/);
});

test("all history checkpoints remain reachable through bounded pagination", () => {
  assert.match(api, /getGroupExportHistory:[\s\S]*?page = 1/);
  assert.match(api, /params: \{ kind, page, page_size: 25 \}/);
  assert.match(dialog, /Download history \{historyPage\}\/\{history\.data\.total_pages\}/);
  assert.match(dialog, /aria-label="Newer download history page"/);
  assert.match(dialog, /aria-label="Older download history page"/);
});

test("the export dialog traps focus and restores document scrolling", () => {
  assert.match(dialog, /dialogRef\.current\?\.querySelectorAll<HTMLElement>/);
  assert.match(dialog, /event\.key !== "Tab"/);
  assert.match(dialog, /document\.body\.style\.overflow = "hidden"/);
  assert.match(dialog, /document\.body\.style\.overflow = priorOverflow/);
});

test("Excel export offers fixed International Airport grouping", () => {
  assert.match(api, /grouping_fields: PassportGroupExportGroupingOption\[\]/);
  assert.match(
    dialog,
    /field\.fixed \|\| selectedFields\.includes\(field\.key\)/,
  );
  assert.match(dialog, /groupByField !== "international_airport"/);
  assert.match(dialog, /groupByField: groupByField \|\| "none"/);
});
