import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

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
const workspaceDialogs = readFileSync(
  new URL("./document-workspace-dialogs.tsx", import.meta.url),
  "utf8",
);
const uploadPanel = readFileSync(new URL("./document-upload-panel.tsx", import.meta.url), "utf8");
const laneNavigation = readFileSync(
  new URL("./flight-ticket-lane-navigation.tsx", import.meta.url),
  "utf8",
);
const distributionRoute = readFileSync(
  new URL(
    "../../../../backend/app/presentation/api/v1/routes/document_distribution.py",
    import.meta.url,
  ),
  "utf8",
);
const batchingModule = await import(
  `data:text/javascript;base64,${Buffer.from(
    ts.transpileModule(batching, {
      compilerOptions: {
        module: ts.ModuleKind.ESNext,
        target: ts.ScriptTarget.ES2022,
      },
    }).outputText,
  ).toString("base64")}`
);
const {
  MAX_DOCUMENT_VERIFICATION_CHUNK_FILES,
  MAX_DOCUMENT_VERIFICATION_CONCURRENCY,
  MAX_DOCUMENT_RECEIPT_CHUNK_BYTES,
  canFinalizeDocumentReceiptChunk,
  createAcceptedDocumentUploadSession,
  createDocumentUploadSession,
  createDocumentVerificationSession,
  isPassengerMatchedVerificationFile,
  runConcurrentDocumentVerification,
} = batchingModule;

function pdfFiles(count, size = 1) {
  return Array.from({ length: count }, (_, index) => ({
    name: `visa-${index + 1}.pdf`,
    size,
    type: "application/pdf",
  }));
}

function createSession(files) {
  let nextId = 0;
  return createDocumentUploadSession(files, () => `upload-${nextId++}`);
}

test("one 1500-file selection is partitioned into bounded resumable chunks", () => {
  assert.match(batching, /MAX_DOCUMENT_SELECTION_FILES = 1_500/);
  assert.match(batching, /MAX_DOCUMENT_SELECTION_BYTES = 2 \* 1024 \* 1024 \* 1024/);
  assert.match(batching, /MAX_DOCUMENT_CHUNK_FILES = 50/);
  assert.match(batching, /TARGET_DOCUMENT_CHUNK_BYTES = 24 \* 1024 \* 1024/);
  assert.match(batching, /completedChunks: number/);
  assert.match(batching, /let chunkIndex = session\.completedChunks/);
  assert.match(batching, /session\.completedChunks = chunkIndex \+ 1/);
  assert.match(batching, /complete PDF selection exceeds the 2 GB safety limit/);
});

test("the client sends up to 50 PDFs and moves the 51st into the next sequential chunk", () => {
  assert.deepEqual(createSession(pdfFiles(50)).chunks.map((chunk) => chunk.length), [50]);
  assert.deepEqual(createSession(pdfFiles(51)).chunks.map((chunk) => chunk.length), [50, 1]);
});

test("the 24 MiB target splits a chunk before the 50-file ceiling", () => {
  const twelveMiB = 12 * 1024 * 1024;
  const session = createSession([
    ...pdfFiles(2, twelveMiB),
    ...pdfFiles(1, 1),
  ]);

  assert.deepEqual(session.chunks.map((chunk) => chunk.length), [2, 1]);
  assert.equal(
    session.chunks[0].reduce((total, file) => total + file.size, 0),
    24 * 1024 * 1024,
  );
});

test("verification uses the largest file chunk inside the bounded OCR envelope", () => {
  let nextId = 0;
  const session = createDocumentVerificationSession(
    pdfFiles(30, 512 * 1024),
    () => `verify-${nextId++}`,
  );

  assert.equal(MAX_DOCUMENT_VERIFICATION_CHUNK_FILES, 16);
  assert.equal(MAX_DOCUMENT_VERIFICATION_CONCURRENCY, 1);
  assert.deepEqual(session.chunks.map((chunk) => chunk.length), [16, 14]);
});

test("verification keeps the 8 MiB byte cap when PDFs are larger", () => {
  let nextId = 0;
  const fiveMiB = 5 * 1024 * 1024;
  const session = createDocumentVerificationSession(
    pdfFiles(2, fiveMiB),
    () => `verify-bytes-${nextId++}`,
  );

  assert.deepEqual(session.chunks.map((chunk) => chunk.length), [1, 1]);
});

test("verification can process chunks sequentially, preserves order, and reports committed files", async () => {
  let nextId = 0;
  const session = createDocumentVerificationSession(
    pdfFiles(18, 1),
    () => `parallel-${nextId++}`,
  );
  let active = 0;
  let maxActive = 0;
  const progress = [];

  const results = await runConcurrentDocumentVerification({
    session,
    concurrency: 1,
    onProgress: (value) => progress.push(value),
    uploadChunk: async (chunk, chunkIndex, reportUpload) => {
      active += 1;
      maxActive = Math.max(maxActive, active);
      reportUpload(chunk.length, chunk.length);
      await new Promise((resolve) => setTimeout(resolve, 5 * (3 - chunkIndex)));
      active -= 1;
      return `chunk-${chunkIndex}`;
    },
  });

  assert.equal(maxActive, 1);
  assert.deepEqual(results, ["chunk-0", "chunk-1"]);
  assert.equal(session.completedChunks, 2);
  assert.equal(progress.at(-1).completedFiles, 18);
  assert.equal(progress.at(-1).percent, 100);
  assert.ok(progress.some((value) => value.completedFiles > 0 && value.completedFiles < 18));
  assert.ok(progress.every((value, index) => index === 0 || value.percent >= progress[index - 1].percent));
});

test("verification drains already-started requests before returning an error", async () => {
  let nextId = 0;
  const session = createDocumentVerificationSession(
    pdfFiles(32, 1),
    () => `drain-${nextId++}`,
  );
  let secondRequestDrained = false;

  await assert.rejects(
    runConcurrentDocumentVerification({
      session,
      concurrency: 2,
      uploadChunk: async (_chunk, chunkIndex) => {
        if (chunkIndex === 0) {
          await new Promise((resolve) => setTimeout(resolve, 2));
          throw new Error("first request failed");
        }
        await new Promise((resolve) => setTimeout(resolve, 15));
        secondRequestDrained = true;
        return "drained";
      },
    }),
    /first request failed/,
  );

  assert.equal(secondRequestDrained, true);
});

test("accepted files retain their verification upload and chunk identities", () => {
  const sourceSession = createSession(pdfFiles(101));
  const acceptedByChunk = sourceSession.chunks.map((chunk, chunkIndex) =>
    chunk.map((_file, fileIndex) =>
      chunkIndex === 0 ? fileIndex === 0 || fileIndex === 49 : chunkIndex === 2,
    ),
  );

  const acceptedSession = createAcceptedDocumentUploadSession(
    sourceSession,
    acceptedByChunk,
  );

  assert.equal(acceptedSession.uploadId, sourceSession.uploadId);
  assert.deepEqual(acceptedSession.chunkIds, [
    sourceSession.chunkIds[0],
    sourceSession.chunkIds[2],
  ]);
  assert.deepEqual(acceptedSession.chunks.map((chunk) => chunk.length), [2, 1]);
  assert.deepEqual(
    acceptedSession.chunks.flat().map((file) => file.name),
    ["visa-1.pdf", "visa-50.pdf", "visa-101.pdf"],
  );
  assert.equal(acceptedSession.totalFiles, 3);
  assert.equal(acceptedSession.totalBytes, 3);
  assert.equal(acceptedSession.completedChunks, 0);
});

test("only verified files with a confirmed passenger match are uploadable", () => {
  assert.equal(
    isPassengerMatchedVerificationFile({
      accepted: true,
      matched_passenger_id: "passenger-1",
      matched_passenger_ids: ["passenger-1"],
      match_status: "matched",
    }),
    true,
  );
  assert.equal(
    isPassengerMatchedVerificationFile({
      accepted: true,
      matched_passenger_id: null,
      matched_passenger_ids: [],
      match_status: "needs_review",
    }),
    false,
  );
});

test("receipt finalization is bounded by aggregate UTF-8 bytes", () => {
  assert.equal(MAX_DOCUMENT_RECEIPT_CHUNK_BYTES, 8 * 1024 * 1024);
  assert.equal(canFinalizeDocumentReceiptChunk(["receipt"], 1), true);
  assert.equal(canFinalizeDocumentReceiptChunk([null], 1), false);
  assert.equal(canFinalizeDocumentReceiptChunk(["receipt"], 2), false);

  const exactLimit = "é".repeat(MAX_DOCUMENT_RECEIPT_CHUNK_BYTES / 2);
  assert.equal(canFinalizeDocumentReceiptChunk([exactLimit], 1), true);
  assert.equal(canFinalizeDocumentReceiptChunk([`${exactLimit}a`], 1), false);
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

test("distribution verification binds receipts to the exact upload and chunk session", () => {
  const verifySource = distributionApi.slice(
    distributionApi.indexOf("verifyDocuments"),
    distributionApi.indexOf("uploadDocuments"),
  );
  assert.match(verifySource, /formData\.append\("upload_id", session\.uploadId\)/);
  assert.match(
    verifySource,
    /formData\.append\("chunk_id", session\.chunkIds\[chunkIndex\]\)/,
  );
  assert.match(verifySource, /createAcceptedDocumentUploadSession/);
  assert.match(verifySource, /createDocumentVerificationSession/);
  assert.match(verifySource, /runConcurrentDocumentVerification/);
  assert.match(verifySource, /MAX_DOCUMENT_VERIFICATION_CONCURRENCY/);
  assert.match(verifySource, /isPassengerMatchedVerificationFile/);
  assert.match(verifySource, /staging_receipt: null/);
  assert.match(workspace, /setVerification\(data\.verification\)/);
  assert.match(workspace, /setUploadSession\(data\.uploadSession\)/);
  assert.doesNotMatch(workspace, /createDocumentUploadSession\(acceptedFiles\)/);
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
  assert.match(workspaceDialogs, /Discard incomplete/);
  assert.match(workspace, /AbortIncompleteUploadDialog/);
  assert.match(workspace, /abortUploads\.mutate\(processingUploadIds/);
});

test("new selection and save remain blocked until incomplete uploads are resolved", () => {
  assert.match(uploadPanel, /const operationPending = uploadPending \|\| verifyPending/);
  assert.match(uploadPanel, /disabled=\{hasIncompleteUploads \|\| operationPending\}/);
  assert.match(workspace, /hasIncompleteUploads && !canResumeCurrentUpload/);
  assert.match(
    workspace,
    /review\.data\.status === "saved" \|\| hasIncompleteUploads/,
  );
  assert.match(
    workspaceDialogs,
    /Completed and saved document lists are not changed\./,
  );
});

test("route-driven document lanes cannot change while type-scoped work is pending", () => {
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
  assert.match(workspace, /operationPending=\{documentTypeOperationPending\}/);
  assert.match(laneNavigation, /aria-disabled=\{operationPending\}/);
  assert.match(laneNavigation, /hasUncommittedSelection/);
  assert.match(laneNavigation, /window\.confirm/);
  assert.match(laneNavigation, /event\.preventDefault\(\)/);
  assert.doesNotMatch(workspace, /setSelectedType/);
  assert.doesNotMatch(workspace, /changeDocumentType/);
});

test("distribution distinguishes physical files from assigned passengers and surfaces reasons first", () => {
  assert.match(distributionTypes, /physical_file_count: number/);
  assert.match(distributionTypes, /assigned_file_count: number/);
  assert.match(distributionTypes, /assigned_passenger_count: number/);
  assert.match(distributionTypes, /assignment_issues: DocumentAssignmentIssue\[\]/);
  assert.match(workspace, /files assigned across \{assignedPassengerCount\} passengers/);
  assert.match(workspace, /Needs assignment \(\{needsAssignmentCount\}\)/);
  assert.match(workspace, /Multiple files can be correctly assigned to the same passenger/);
  assert.match(workspace, /\{issue\.reason\}/);
  assert.doesNotMatch(workspace, /<h3[^>]*>Needs Manual Review<\/h3>/);
});

test("document delivery polling follows active work and stops after webhook grace", () => {
  assert.match(distributionTypes, /poll_after_seconds: number \| null/);
  assert.match(distributionApi, /params: \{ limit: 6 \}/);
  assert.match(distributionHooks, /query\.state\.data\?\.poll_after_seconds/);
  assert.match(distributionHooks, /seconds \* 1_000 : false/);
  assert.match(distributionHooks, /refetchIntervalInBackground: false/);
  assert.match(distributionHooks, /gcTime: 0/);
  assert.match(distributionRoute, /DOCUMENT_DELIVERY_WEBHOOK_GRACE = timedelta\(minutes=5\)/);
  assert.match(distributionRoute, /limit: Annotated\[int, Query\(ge=0, le=100\)\] = 100/);
  assert.match(distributionRoute, /\.limit\(limit\)/);
});

test("distribution finalizes opaque verification receipts without retransmitting PDF bytes", () => {
  assert.match(distributionTypes, /staging_receipt: string \| null/);
  assert.match(distributionApi, /formData\.append\("staging_receipts", receipt\)/);
  assert.match(distributionApi, /if \(canFinalizeStaging\)/);
  assert.match(distributionApi, /chunk\.forEach\(\(file\) => formData\.append\("files", file\)\)/);
  assert.match(workspace, /acceptedStagingReceipts/);
  assert.match(workspace, /stagingReceipts: acceptedStagingReceipts/);
  assert.doesNotMatch(workspace, /\u00e2\u20ac\u201d/);
});

test("expired or oversized receipt chunks fall back safely to raw PDF bytes", () => {
  assert.match(distributionApi, /canFinalizeDocumentReceiptChunk/);
  assert.match(distributionApi, /return await postChunk\(chunkReceipts\)/);
  assert.match(distributionApi, /code !== "HTTP_410"/);
  assert.match(distributionApi, /return postChunk\(\)/);
  assert.doesNotMatch(distributionApi, /code !== "HTTP_409"/);
});
