import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  chunkEcrEntries, createEcrUploadEntries, restoreEcrUpload, storeEcrUpload,
  uploadEcrEntries, validateEcrFiles, type EcrUploadEntry, type EcrUploadProgress,
} from "./ecr-upload";

const file = (name = "passport.jpg", size = 100) => {
  const value = new File(["test-image"], name, { type: "image/jpeg", lastModified: 123 });
  Object.defineProperty(value, "size", { value: size });
  return value;
};

describe("ECR bulk image uploads", () => {
  beforeEach(() => sessionStorage.clear());

  it("keeps all 1000 files and duplicate names as distinct stable IDs", () => {
    const entries = createEcrUploadEntries(Array.from({ length: 1000 }, () => file()));
    expect(entries).toHaveLength(1000);
    expect(new Set(entries.map((entry) => entry.clientId)).size).toBe(1000);
    expect(chunkEcrEntries(entries)).toHaveLength(200);
    expect(() => createEcrUploadEntries(Array.from({ length: 1001 }, () => file()))).toThrow("1,000");
  });

  it("rejects unsupported, empty and oversized files before making a batch", () => {
    expect(() => validateEcrFiles([new File(["pdf"], "page.pdf", { type: "application/pdf" })])).toThrow("JPG");
    expect(() => validateEcrFiles([file("empty.jpg", 0)])).toThrow("non-empty");
    expect(() => validateEcrFiles([file("huge.jpg", 10 * 1024 * 1024 + 1)])).toThrow("10 MB");
  });

  it("bounds both request bytes and file count", () => {
    const entries = createEcrUploadEntries(Array.from({ length: 11 }, () => file("large.jpg", 8 * 1024 * 1024)));
    expect(chunkEcrEntries(entries).map((chunk) => chunk.length)).toEqual([2, 2, 2, 2, 2, 1]);
  });

  it("restores the original identities after reselecting reordered files, including duplicates", () => {
    const original = [file("same.jpg"), file("different.jpg", 200), file("same.jpg")];
    const entries = createEcrUploadEntries(original);
    storeEcrUpload("batch", entries);
    const restored = restoreEcrUpload("batch", [original[2], original[0], original[1]]);
    expect(restored.map((entry) => entry.clientId)).toEqual(entries.map((entry) => entry.clientId));
    expect(restored.map((entry) => entry.file.name)).toEqual(original.map((entry) => entry.name));
    expect(() => restoreEcrUpload("batch", [file("wrong.jpg"), original[1], original[2]])).toThrow("same original images");
  });

  it("uploads at most three chunks simultaneously and skips already saved identities", async () => {
    const entries = createEcrUploadEntries(Array.from({ length: 28 }, (_, index) => file(`${index}.jpg`)));
    const upload = vi.fn(async (chunk: EcrUploadEntry[], report: (fraction: number) => void) => {
      active++;
      maximum = Math.max(maximum, active);
      report(1);
      await new Promise((resolve) => setTimeout(resolve, 2));
      active--;
      uploaded.push(...chunk);
    });
    let active = 0;
    let maximum = 0;
    const uploaded: EcrUploadEntry[] = [];
    const progress: EcrUploadProgress[] = [];
    await uploadEcrEntries({
      entries,
      existingItems: entries.slice(0, 3).map((entry) => ({ client_id: entry.clientId })),
      uploadChunk: upload,
      onProgress: (value) => progress.push(value),
      signal: new AbortController().signal,
    });
    expect(maximum).toBe(3);
    expect(upload).toHaveBeenCalledTimes(5);
    expect(uploaded).toHaveLength(25);
    expect(uploaded.some((entry) => entry.clientId === entries[0].clientId)).toBe(false);
    expect(progress.at(-1)).toEqual({ completed: 28, total: 28, percent: 100 });
    expect(progress.find((value) => value.completed === 3)?.percent).toBeLessThan(100);
  });

  it("settles in-flight chunks before exposing a failure and stops starting more chunks", async () => {
    const entries = createEcrUploadEntries(Array.from({ length: 30 }, () => file()));
    let settled = 0;
    const upload = vi.fn(async () => {
      if (upload.mock.calls.length === 1) throw new Error("Connection lost");
      await new Promise((resolve) => setTimeout(resolve, 2));
      settled++;
    });
    await expect(uploadEcrEntries({ entries, existingItems: [], uploadChunk: upload, onProgress: vi.fn(), signal: new AbortController().signal })).rejects.toThrow("Connection lost");
    expect(upload).toHaveBeenCalledTimes(3);
    expect(settled).toBe(2);
  });
});
