import { AxiosError, type AxiosAdapter } from "axios";
import { useEffect, useState } from "react";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import apiClient from "@/lib/api/client";
import type { OwnerBoundRequestConfig } from "@/lib/api/request-owner";
import { AuthenticatedContent } from "@/features/auth/components/authenticated-content";
import { SessionLifecycle } from "@/providers/session-lifecycle";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import type { RenameDocumentBatch } from "@/types/document-rename.types";
import { DocumentRenamePage } from "../components/document-rename-page";

export const renameActor: User = {
  id: "11111111-1111-4111-8111-111111111111", email: "rename-a@example.test",
  full_name: "Synthetic A", role: "agency_admin",
  agency_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", is_active: true,
  created_at: "2026-10-01", updated_at: "2026-10-01", last_login_at: null,
};
export const nextRenameActor = { ...renameActor, id: "22222222-2222-4222-8222-222222222222", email: "rename-b@example.test" };
export const renameBatch: RenameDocumentBatch = {
  batch_id: "synthetic-rename", title: "Synthetic trip", status: "completed",
  total_count: 1, visa_count: 1, ticket_count: 0, unknown_count: 0,
  zip_download_url: "/synthetic.zip", created_at: "2026-10-01", items: [],
};
type Failure = "list" | "open" | "delete" | null;

/** Only the final Axios network delegate is synthetic; actual auth/client gates execute. */
export function createRenameAuthorityContext(failure: Failure = null) {
  const gate = Promise.withResolvers<void>();
  const entered: unknown[] = [], settled: unknown[] = [];
  const mounts: string[] = [], unmounts: string[] = [];
  const writes: Array<{ path: string; actor: string; authority?: string; filenames: string[];
    uploadId?: FormDataEntryValue | null; chunkId?: FormDataEntryValue | null;
    chunkIndex?: FormDataEntryValue | null; expectedFiles?: FormDataEntryValue | null }> = [];
  let currentFailure = failure;
  let deleted = false;
  const previousAdapter = apiClient.defaults.adapter;
  const adapter: AxiosAdapter = async config => {
    const path = config.url ?? "";
    if (!path.startsWith("/api/v1/document-rename/batches")) throw new Error("Unexpected synthetic request: " + path);
    const isList = config.method === "get" && path === "/api/v1/document-rename/batches";
    const isDelete = path.endsWith("bulk-delete");
    const isOpen = config.method === "get" && !isList;
    if ((currentFailure === "list" && isList) || (currentFailure === "open" && isOpen) || (currentFailure === "delete" && isDelete)) {
      throw new AxiosError("Synthetic service unavailable", undefined, config, undefined, {
        data: { error: { code: "SYNTHETIC_UNAVAILABLE", message: "Synthetic rename service unavailable" } },
        status: 503, statusText: "Unavailable", headers: {}, config,
      });
    }
    if (config.method === "post") {
      const files = config.data instanceof FormData ? config.data.getAll("files") as File[] : [];
      writes.push({ path, actor: String(config.headers.get("X-Expected-Actor-Id")),
        authority: (config as OwnerBoundRequestConfig).expectedAuthorityKey,
        filenames: files.map(file => file.name),
        ...(config.data instanceof FormData ? {
          uploadId: config.data.get("upload_id"), chunkId: config.data.get("chunk_id"),
          chunkIndex: config.data.get("chunk_index"), expectedFiles: config.data.get("expected_file_count"),
        } : {}) });
      if (isDelete) deleted = true;
    }
    const data = isList ? deleted ? [] : [renameBatch]
      : isDelete ? { deleted_count: 1, deleted_storage_objects: 1 } : renameBatch;
    return { data, status: 200, statusText: "OK", headers: {}, config };
  };
  const client = new QueryClient({
    mutationCache: new MutationCache({
      onMutate: async variables => { entered.push(variables); await gate.promise; },
      onSettled: (_data, error) => { settled.push(error); },
    }),
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  apiClient.defaults.adapter = adapter;
  function Page() {
    const [actor] = useState(() => useAuthStore.getState().user!.id);
    useEffect(() => { mounts.push(actor); return () => { unmounts.push(actor); }; }, [actor]);
    return <><output data-testid="rename-page-owner">{actor}</output><DocumentRenamePage /></>;
  }
  return {
    client, entered, settled, mounts, unmounts, writes, release: () => gate.resolve(),
    setFailure: (value: Failure) => { currentFailure = value; },
    mount: () => render(<QueryClientProvider client={client}><SessionLifecycle queryClient={client} />
      <AuthenticatedContent><Page /></AuthenticatedContent></QueryClientProvider>),
    cleanup: () => { client.clear(); apiClient.defaults.adapter = previousAdapter; },
  };
}
