import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const batching = readFileSync(
  new URL("../services/document-upload-batching.ts", import.meta.url),
  "utf8",
);
const renameApi = readFileSync(new URL("../api/document-rename.api.ts", import.meta.url), "utf8");
const distributionApi = readFileSync(
  new URL("../api/document-distribution.api.ts", import.meta.url),
  "utf8",
);
const distributionHooks = readFileSync(
  new URL("../hooks/use-document-distribution.ts", import.meta.url),
  "utf8",
);
const endpoints = readFileSync(new URL("../../../lib/api/endpoints.ts", import.meta.url), "utf8");
const distributionTypes = readFileSync(
  new URL("../../../types/document-distribution.types.ts", import.meta.url),
  "utf8",
);
const renamePage = readFileSync(new URL("./document-rename-page.tsx", import.meta.url), "utf8");
const workspace = readFileSync(new URL("./document-workspace.tsx", import.meta.url), "utf8");

test("one 1500-file selection is partitioned into bounded resumable chunks", () => {
  assert.match(batching, /MAX_DOCUMENT_SELECTION_FILES = 1_500/);
  assert.match(batching, /MAX_DOCUMENT_SELECTION_BYTES = 2 \* 1024 \* 1024 \* 1024/);
  assert.match(batching, /MAX_DOCUMENT_CHUNK_FILES = 25/);
  assert.match(batching, /TARGET_DOCUMENT_CHUNK_BYTES = 24 \* 1024 \* 1024/);
  assert.match(batching, /completedChunks: number/);
  assert.match(batching, /let chunkIndex = session\.completedChunks/);
  assert.match(batching, /session\.completedChunks = chunkIndex \+ 1/);
  assert.match(batching, /complete PDF selection exceeds the 2 GB safety limit/);
});

test("rename and distribution send one immutable upload manifest", () => {
  for (const source of [renameApi, distributionApi]) {
    assert.match(source, /formData\.append\("upload_id", session\.uploadId\)/);
    assert.match(source, /formData\.append\("chunk_id", session\.chunkIds\[chunkIndex\]\)/);
    assert.match(source, /formData\.append\("expected_chunk_count"/);
    assert.match(source, /formData\.append\("expected_file_count"/);
    assert.match(source, /runChunkedDocumentUpload/);
  }
});

test("progress reflects committed files and contains no synthetic 88 or 92 percent timer", () => {
  assert.doesNotMatch(renamePage, /current >= 92/);
  assert.doesNotMatch(workspace, /current >= 88/);
  assert.match(renamePage, /progressDetail\.completedFiles/);
  assert.match(workspace, /progressDetail\.completedFiles/);
  assert.match(batching, /phase: uploadedFraction >= 1 \? "processing" : "uploading"/);
});

test("every incomplete distribution upload is surfaced and can be explicitly discarded", () => {
  assert.match(distributionTypes, /processing_upload_ids: string\[\]/);
  assert.match(endpoints, /uploads\/\$\{batchId\}\/abort/);
  assert.match(distributionApi, /abortUpload: async/);
  assert.match(distributionApi, /apiClient\.post<AbortDocumentUploadResult>/);
  assert.match(distributionHooks, /useAbortDistributionUploads/);
  assert.match(distributionHooks, /for \(const batchId of uniqueBatchIds\)/);
  assert.match(workspace, /review\.data\?\.processing_upload_ids \?\? \[\]/);
  assert.match(workspace, /Discard incomplete/);
  assert.match(workspace, /AbortIncompleteUploadDialog/);
  assert.match(workspace, /abortUploads\.mutate\(processingUploadIds/);
});

test("new selection and save remain blocked until incomplete uploads are resolved", () => {
  assert.match(workspace, /disabled=\{hasIncompleteUploads \|\| upload\.isPending \|\| verify\.isPending\}/);
  assert.match(workspace, /hasIncompleteUploads && !canResumeCurrentUpload/);
  assert.match(
    workspace,
    /review\.data\.status === "saved" \|\| hasIncompleteUploads/,
  );
  assert.match(
    workspace,
    /Completed and saved document lists are not changed\./,
  );
});

test("document type cannot change while type-scoped work is pending and safe switches clear stale state", () => {
  assert.match(workspace, /const documentTypeOperationPending =/);
  for (const pendingState of [
    "verify.isPending",
    "upload.isPending",
    "abortUploads.isPending",
    "reupload.isPending",
    "deleteDocuments.isPending",
    "unassignDocuments.isPending",
    "save.isPending",
    "sendDocuments.isPending",
  ]) {
    assert.match(workspace, new RegExp(pendingState.replace(".", "\\.")));
  }
  assert.match(workspace, /disabled=\{documentTypeOperationPending\}/);
  assert.match(workspace, /onClick=\{\(\) => changeDocumentType\(item\.type\)\}/);
  assert.match(workspace, /if \(nextType === selectedType \|\| documentTypeOperationPending\) return/);
  assert.match(workspace, /setIsSendPreviewOpen\(false\)/);
  assert.match(workspace, /setDeliveryDocumentIds\(null\)/);
  assert.match(workspace, /verify\.reset\(\)/);
  assert.match(workspace, /sendDocuments\.reset\(\)/);
});
