import { AxiosError, type AxiosAdapter } from "axios";
import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import apiClient from "@/lib/api/client";
import { AuthenticatedContent } from "@/features/auth/components/authenticated-content";
import { SessionLifecycle } from "@/providers/session-lifecycle";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import type { EcrBatch } from "@/types/ecr-checker.types";
import { EcrCheckerPage } from "../components/ecr-checker-page";

export const ecrActor: User = {
  id: "11111111-1111-4111-8111-111111111111", email: "ecr-a@example.test",
  full_name: "Synthetic A", role: "agency_admin",
  agency_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", is_active: true,
  created_at: "2026-10-01", updated_at: "2026-10-01", last_login_at: null,
};
export const replacementEcrActor = { ...ecrActor, id: "22222222-2222-4222-8222-222222222222" };
export const ecrBatch: EcrBatch = {
  batch_id: "synthetic-ecr", title: "Synthetic private ECR batch", status: "completed_with_errors",
  total_count: 1, expected_count: 1, processed_count: 1, ecr_count: 0, na_count: 0,
  review_count: 0, failed_count: 1, created_at: "2026-10-01", items: [],
};
const ROOT = "/api/v1/ecr-checker/batches";

/** Real client/owner adapter, remount and reset; only network responses are synthetic. */
export function createEcrAuthorityContext(existing = false) {
  const previousAdapter = apiClient.defaults.adapter;
  const writes: Array<{ path: string; actor: string }> = [];
  let currentBatch: EcrBatch = { ...ecrBatch };
  const mounts: string[] = [], unmounts: string[] = [];
  const batchWrites: unknown[] = [];
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const unsubscribe = client.getQueryCache().subscribe(event => {
    if (event.type === "updated" && event.query.queryKey[0] === "ecr-checker"
      && event.query.queryKey[1] === "batch" && event.query.state.data) batchWrites.push(event.query.state.data);
  });
  const adapter: AxiosAdapter = async config => {
    const path = config.url ?? "";
    if (!path.startsWith(ROOT)) throw new Error("Unexpected synthetic ECR request: " + path);
    const isList = config.method === "get" && path === ROOT;
    const user = useAuthStore.getState().user;
    const authorized = user?.id === ecrActor.id && user.role === ecrActor.role && user.agency_id === ecrActor.agency_id;
    if (config.method === "get" && !isList && !authorized) {
      throw new AxiosError("Synthetic batch unavailable", undefined, config, undefined, {
        data: { error: { code: "NOT_FOUND", message: "Synthetic batch unavailable" } },
        status: 404, statusText: "Not found", headers: {}, config,
      });
    }
    if (config.method === "post") writes.push({ path, actor: String(config.headers.get("X-Expected-Actor-Id")) });
    if (config.method === "post") {
      currentBatch = path === ROOT ? { ...ecrBatch, status: "uploading", total_count: 0 }
        : path.endsWith("/start") || path.endsWith("/retry") ? { ...ecrBatch, status: "queued" } : { ...currentBatch, total_count: 1 };
    }
    const data = isList ? [] : currentBatch;
    return { data, status: 200, statusText: "OK", headers: {}, config };
  };
  apiClient.defaults.adapter = adapter;
  function Page() {
    const [actor] = useState(() => useAuthStore.getState().user!.id);
    useEffect(() => { mounts.push(actor); return () => { unmounts.push(actor); }; }, [actor]);
    return <><output data-testid="ecr-page-owner">{actor}</output><EcrCheckerPage initialBatchId={existing ? ecrBatch.batch_id : null} /></>;
  }
  return {
    client, writes, mounts, unmounts, batchWrites,
    mount: () => render(<QueryClientProvider client={client}><SessionLifecycle queryClient={client} />
      <AuthenticatedContent><Page /></AuthenticatedContent></QueryClientProvider>),
    cleanup: () => { unsubscribe(); client.clear(); apiClient.defaults.adapter = previousAdapter; },
  };
}
