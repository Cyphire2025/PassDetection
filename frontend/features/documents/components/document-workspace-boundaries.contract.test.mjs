import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (relativePath) =>
  readFileSync(new URL(relativePath, import.meta.url), "utf8");

const workspace = read("./document-workspace.tsx");
const model = read("./document-workspace-model.ts");
const rows = read("./document-workspace-review-rows.tsx");

test("optional document-workspace surfaces use explicit lazy boundaries", () => {
  assert.match(workspace, /const AbortIncompleteUploadDialog = dynamic\(/);
  assert.match(workspace, /const DocumentDeliveryPreviewDialog = dynamic\(/);
  assert.match(workspace, /const RemoveAssignmentsDialog = dynamic\(/);
  assert.match(workspace, /const DocumentWorkspaceUploadStatus = dynamic\(/);
  assert.match(workspace, /const DocumentWorkspaceReviewControls = dynamic\(/);
  assert.match(workspace, /const DocumentWorkspaceReviewRows = dynamic\(/);
  assert.match(workspace, /const FlightTicketLaneNavigation = dynamic\(/);
  assert.match(workspace, /import\("\.\/document-workspace-dialogs"\)/);
  assert.match(workspace, /import\("\.\/document-workspace-review-rows"\)/);
  assert.match(workspace, /import\("\.\/document-workspace-review-controls"\)/);
  assert.match(workspace, /import\("\.\/document-workspace-upload-status"\)/);
  assert.match(workspace, /import\("\.\/flight-ticket-lane-navigation"\)/);
});

test("the primary upload workflow remains eager and route-owned", () => {
  assert.match(workspace, /import \{\s*DocumentUploadPanel,/);
  assert.doesNotMatch(workspace, /dynamic\([\s\S]*import\("\.\/document-upload-panel"\)/);
  assert.match(workspace, /const documentType = lane\.documentType/);
  assert.match(workspace, /<DocumentUploadPanel/);
});

test("review derivation and row rendering are isolated from the workspace controller", () => {
  assert.match(workspace, /createDocumentReviewModel\(review\.data\)/);
  assert.match(model, /for \(const row of review\.review_rows\)/);
  assert.match(rows, /rows\.map\(\(row\) =>/);
  assert.match(rows, /documentsByPassengerId\.get\(row\.passenger_id\) \?\? \[\]/);
  assert.doesNotMatch(workspace, /visibleReviewRows\.map\(\(row\) =>/);
  assert.doesNotMatch(workspace, /reviewRows\.filter\(/);
});
