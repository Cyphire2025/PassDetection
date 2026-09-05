import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { passportGroupCoordinatorSource as workspace } from "./passport-group-detail-source.contract-helper.mjs";
const documentCell = readFileSync(
  new URL("./passport-document-cell.tsx", import.meta.url),
  "utf8",
);
const documentImport = readFileSync(
  new URL("./passport-document-import-dialog.tsx", import.meta.url),
  "utf8",
);
const tripDetails = readFileSync(
  new URL("./passport-trip-details-dialog.tsx", import.meta.url),
  "utf8",
);
const importHelpers = readFileSync(
  new URL("../utils/passport-document-import.ts", import.meta.url),
  "utf8",
);
const tripHelpers = readFileSync(
  new URL("../utils/passport-group-trip.ts", import.meta.url),
  "utf8",
);

test("optional passport workflows load through explicit module boundaries", () => {
  assert.match(workspace, /dynamic\([\s\S]*?passport-document-import-dialog/);
  assert.match(workspace, /dynamic\([\s\S]*?passport-trip-details-dialog/);
  assert.match(workspace, /role="status"/);
  assert.match(workspace, /aria-live="polite"/);
});

test("the coordinator no longer owns extracted rendering implementations", () => {
  assert.doesNotMatch(workspace, /function DocumentCell\(/);
  assert.doesNotMatch(workspace, /function PassportDocumentImportDialog\(/);
  assert.doesNotMatch(workspace, /function TripDetailsDialog\(/);
  assert.match(documentCell, /export function DocumentCell\(/);
  assert.match(documentImport, /export function PassportDocumentImportDialog\(/);
  assert.match(tripDetails, /export function TripDetailsDialog\(/);
});

test("document and trip normalization helpers have one source of truth", () => {
  assert.match(importHelpers, /export function matchPreviewFiles\(/);
  assert.match(importHelpers, /export function formatBytes\(/);
  assert.match(tripHelpers, /export function normalizeCities\(/);
  assert.doesNotMatch(documentImport, /function matchPreviewFiles\(/);
  assert.doesNotMatch(documentImport, /function formatBytes\(/);
  assert.doesNotMatch(workspace, /function normalizeCities\(/);
  assert.doesNotMatch(tripDetails, /function normalizeCities\(/);
});
