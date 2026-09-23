import { useQuery } from "@tanstack/react-query";
import { ecrCheckerApi } from "../api/ecr-checker.api";

export const ecrKeys = {
  all: ["ecr-checker"] as const,
  batches: ["ecr-checker", "batches"] as const,
  batch: (id: string | null) => ["ecr-checker", "batch", id] as const,
};

export function useEcrBatches() {
  return useQuery({
    queryKey: ecrKeys.batches,
    queryFn: ({ signal }) => ecrCheckerApi.list(signal),
    refetchInterval: (query) => query.state.data?.some((batch) => ["queued", "processing"].includes(batch.status)) ? 10_000 : false,
  });
}

export function useEcrBatch(batchId: string | null) {
  return useQuery({
    queryKey: ecrKeys.batch(batchId),
    queryFn: ({ signal }) => ecrCheckerApi.get(batchId!, signal),
    enabled: Boolean(batchId),
    refetchInterval: (query) => query.state.data && ["uploading", "queued", "processing"].includes(query.state.data.status) ? 3_000 : false,
  });
}
