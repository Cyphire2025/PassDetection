import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { downloadStreamedResponse } from "@/lib/api/streamed-download";
import type { EcrBatch, EcrBatchSummary } from "@/types/ecr-checker.types";
import type { EcrUploadEntry } from "../services/ecr-upload";

const endpoints = API_ENDPOINTS.ecrChecker;

export const ecrCheckerApi = {
  async list(signal?: AbortSignal) {
    return (await apiClient.get<EcrBatchSummary[]>(endpoints.batches, { signal })).data;
  },
  async get(batchId: string, signal?: AbortSignal) {
    return (await apiClient.get<EcrBatch>(endpoints.batch(batchId), { signal })).data;
  },
  async create(title: string, expectedCount: number, signal?: AbortSignal) {
    return (await apiClient.post<EcrBatch>(endpoints.batches, { title: title.slice(0, 160), expected_count: expectedCount }, { signal })).data;
  },
  async upload(batchId: string, entries: EcrUploadEntry[], report: (fraction: number) => void, signal: AbortSignal) {
    const form = new FormData();
    entries.forEach(({ file }) => form.append("files", file));
    form.append("client_ids", JSON.stringify(entries.map(({ clientId }) => clientId)));
    return (await apiClient.post<EcrBatch>(endpoints.items(batchId), form, {
      signal,
      timeout: 180_000,
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress: ({ loaded, total }) => report(total ? loaded / total : 0),
    })).data;
  },
  async start(batchId: string, signal?: AbortSignal) {
    return (await apiClient.post<EcrBatch>(endpoints.start(batchId), undefined, { signal })).data;
  },
  async retry(batchId: string) {
    return (await apiClient.post<EcrBatch>(endpoints.retry(batchId))).data;
  },
  export(batchId: string) {
    return downloadStreamedResponse({
      url: endpoints.export(batchId),
      suggestedFilename: "ECR-results.xlsx",
      maxFallbackBytes: 4 * 1024 * 1024,
    });
  },
};
