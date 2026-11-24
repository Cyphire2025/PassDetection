import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { DocumentStagingManifest } from "../services/document-upload-batching";
import { documentDistributionApi } from "./document-distribution.api";

const http = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: http }));
vi.mock("@/lib/api/streamed-download", () => ({ downloadStreamedResponse: vi.fn() }));

function manifest(count = 2): DocumentStagingManifest {
  return {
    version: 1, uploadId: "synthetic-upload", totalFiles: count, totalBytes: count * 10,
    completedChunks: 0, createdAt: "2026-10-01T00:00:00Z", finalizationStarted: true,
    chunks: Array.from({ length: count }, (_, index) => ({
      chunkId: "synthetic-chunk-" + index, receipts: ["synthetic-receipt-" + index],
      fileCount: 1, totalBytes: 10,
    })),
  };
}

beforeEach(() => vi.resetAllMocks());
afterEach(() => vi.useRealTimers());

it("finalizes receipt-only chunks sequentially and releases each committed capability", async () => {
  const plan = manifest();
  const signal = new AbortController().signal;
  const checkpoints = vi.fn();
  const progress = vi.fn();
  const review = { batch_id: "synthetic-batch", status: "saved" };
  http.post.mockImplementation(async (_url, body: FormData, config) => {
    expect(body.getAll("files")).toEqual([]);
    expect(body.get("upload_id")).toBe(plan.uploadId);
    expect(body.get("expected_chunk_count")).toBe("2");
    expect(body.get("expected_file_count")).toBe("2");
    expect(config.signal).toBe(signal);
    return { data: review };
  });
  expect(await documentDistributionApi.uploadDocuments("synthetic-group", "visa", plan, progress, checkpoints, signal)).toBe(review);
  expect(http.post.mock.calls.map(call => call[1].get("chunk_id"))).toEqual(["synthetic-chunk-0", "synthetic-chunk-1"]);
  expect(http.post.mock.calls.map(call => call[1].getAll("staging_receipts"))).toEqual([["synthetic-receipt-0"], ["synthetic-receipt-1"]]);
  expect(checkpoints.mock.calls.map(call => call[0].completedChunks)).toEqual([1, 2]);
  expect(plan.chunks.every(chunk => chunk.receipts.length === 0)).toBe(true);
  expect(progress.mock.calls.at(-1)?.[0]).toMatchObject({ percent: 100, phase: "completed", completedFiles: 2 });
});

it("resumes from the committed checkpoint without resending an earlier chunk", async () => {
  const plan = manifest();
  plan.completedChunks = 1;
  plan.chunks[0].receipts = [];
  http.post.mockResolvedValue({ data: { batch_id: "synthetic-batch" } });
  await documentDistributionApi.uploadDocuments("synthetic-group", "visa", plan);
  expect(http.post).toHaveBeenCalledTimes(1);
  expect(http.post.mock.calls[0][1].get("chunk_index")).toBe("1");
  expect(http.post.mock.calls[0][1].get("chunk_id")).toBe("synthetic-chunk-1");
});

it("does not turn an expired staging receipt into raw-file fallback or a committed checkpoint", async () => {
  const plan = manifest(1);
  const checkpoints = vi.fn();
  http.post.mockRejectedValue({ code: "HTTP_410" });
  await expect(documentDistributionApi.uploadDocuments("synthetic-group", "visa", plan, undefined, checkpoints))
    .rejects.toThrow("browser did not retain raw file copies");
  expect(http.post).toHaveBeenCalledTimes(1);
  expect(http.post.mock.calls[0][1].getAll("files")).toEqual([]);
  expect(checkpoints).not.toHaveBeenCalled();
  expect(plan.completedChunks).toBe(0);
  expect(plan.chunks[0].receipts).toEqual(["synthetic-receipt-0"]);
});

it("stops before the next dispatch when the current operation is cancelled after a commit", async () => {
  const plan = manifest();
  const controller = new AbortController();
  http.post.mockResolvedValue({ data: { batch_id: "synthetic-batch" } });
  await expect(documentDistributionApi.uploadDocuments("synthetic-group", "visa", plan, undefined,
    () => controller.abort(), controller.signal)).rejects.toMatchObject({ name: "AbortError" });
  expect(http.post).toHaveBeenCalledTimes(1);
  expect(plan.completedChunks).toBe(1);
  expect(plan.chunks[1].receipts).toEqual(["synthetic-receipt-1"]);
});

it("retries a lost response with the same upload, chunk and receipt identities", async () => {
  vi.useFakeTimers();
  const plan = manifest(1);
  http.post.mockRejectedValueOnce({ code: "NETWORK_ERROR" }).mockResolvedValue({ data: { batch_id: "synthetic-batch" } });
  const pending = documentDistributionApi.uploadDocuments("synthetic-group", "visa", plan);
  await vi.advanceTimersByTimeAsync(400);
  await expect(pending).resolves.toMatchObject({ batch_id: "synthetic-batch" });
  expect(http.post).toHaveBeenCalledTimes(2);
  const bodies = http.post.mock.calls.map(call => Array.from((call[1] as FormData).entries()));
  expect(bodies[1]).toEqual(bodies[0]);
  expect(plan.completedChunks).toBe(1);
});
