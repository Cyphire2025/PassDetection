import assert from "node:assert/strict";
import test from "node:test";
import {
  createDocumentUploadSession,
  createDocumentVerificationSession,
  runChunkedDocumentUpload,
  runConcurrentDocumentVerification,
  runStagedDocumentUpload,
} from "./document-upload-batching.ts";

const files = count => Array.from({ length: count }, (_, index) => ({
  name: `synthetic-${index}.pdf`, size: index + 1, type: "application/pdf",
}));
const manifest = () => ({
  version: 1, uploadId: "synthetic-upload", totalFiles: 2, totalBytes: 20,
  completedChunks: 0, createdAt: "2026-10-01",
  chunks: [
    { chunkId: "first", receipts: ["receipt-a"], fileCount: 1, totalBytes: 10 },
    { chunkId: "second", receipts: ["receipt-b"], fileCount: 1, totalBytes: 10 },
  ],
});

test("raw transient retries preserve one chunk identity and reserve completion for acknowledgement", async t => {
  const schedule = globalThis.setTimeout;
  const delays = [];
  t.mock.method(globalThis, "setTimeout", (callback, delay) => {
    delays.push(delay);
    return schedule(callback, 0);
  });
  let nextId = 0;
  const session = createDocumentUploadSession(files(51), () => `id-${nextId++}`);
  const originalIds = [...session.chunkIds];
  const calls = [], progress = [];
  let failures = 2;
  const result = await runChunkedDocumentUpload({
    session,
    onProgress: value => progress.push(value),
    uploadChunk: async (_files, index, report) => {
      calls.push([index, session.chunkIds[index]]);
      report(1, 1);
      assert.ok(progress.at(-1).percent < 100);
      if (failures-- > 0) throw { code: "HTTP_503" };
      return index;
    },
  });
  assert.equal(result, 1);
  assert.deepEqual(calls.map(([index]) => index), [0, 0, 0, 1]);
  assert.deepEqual(calls.map(([, id]) => id), [originalIds[0], originalIds[0], originalIds[0], originalIds[1]]);
  assert.deepEqual(delays, [400, 800]);
  assert.equal(session.completedChunks, 2);
  assert.equal(progress.at(-1).percent, 100);
  assert.ok(progress.every((value, index) => index === 0 || value.percent >= progress[index - 1].percent));
});

test("aborting a staged retry delay preserves all unacknowledged receipts and starts no retry", async t => {
  const controller = new AbortController();
  const schedule = globalThis.setTimeout;
  t.mock.method(globalThis, "setTimeout", (callback, delay) => {
    const timer = schedule(callback, delay);
    if (delay === 400) queueMicrotask(() => controller.abort("route-closed"));
    return timer;
  });
  const pending = manifest();
  let calls = 0;
  await assert.rejects(runStagedDocumentUpload({
    manifest: pending, signal: controller.signal,
    uploadChunk: async () => { calls++; throw { code: "NETWORK_ERROR" }; },
  }), { name: "AbortError" });
  assert.equal(calls, 1);
  assert.equal(pending.completedChunks, 0);
  assert.deepEqual(pending.chunks.map(chunk => chunk.receipts), [["receipt-a"], ["receipt-b"]]);
});

test("a permanent second-chunk failure resumes only its original receipt roster", async () => {
  const pending = manifest();
  const snapshots = [], calls = [];
  await assert.rejects(runStagedDocumentUpload({
    manifest: pending,
    onManifestChange: value => snapshots.push(value),
    uploadChunk: async chunk => {
      calls.push(chunk.chunkId);
      if (chunk.chunkId === "second") throw { code: "HTTP_409" };
      return "first acknowledgement";
    },
  }), { code: "HTTP_409" });
  assert.equal(pending.completedChunks, 1);
  assert.deepEqual(pending.chunks.map(chunk => chunk.receipts), [[], ["receipt-b"]]);
  assert.deepEqual(calls, ["first", "second"]);
  const resumed = await runStagedDocumentUpload({
    manifest: pending,
    uploadChunk: async chunk => {
      calls.push(chunk.chunkId);
      assert.deepEqual(chunk.receipts, ["receipt-b"]);
      return "second acknowledgement";
    },
  });
  assert.equal(resumed, "second acknowledgement");
  assert.deepEqual(calls, ["first", "second", "second"]);
  assert.deepEqual(snapshots[0].chunks.map(chunk => chunk.receipts), [[], ["receipt-b"]]);
  assert.deepEqual(pending.chunks.map(chunk => chunk.receipts), [[], []]);
});

test("verification releases only acknowledged File chunks when a later chunk fails", async () => {
  const session = createDocumentVerificationSession(files(17));
  const secondChunk = session.chunks[1];
  await assert.rejects(runConcurrentDocumentVerification({
    session, concurrency: 1,
    uploadChunk: async (_files, index) => {
      if (index === 1) throw new Error("Synthetic parser failure");
      return "durable receipt ownership";
    },
  }), /Synthetic parser failure/);
  assert.deepEqual(session.chunks[0], []);
  assert.equal(session.chunks[1], secondChunk);
  assert.equal(session.completedChunks, 0);
});
