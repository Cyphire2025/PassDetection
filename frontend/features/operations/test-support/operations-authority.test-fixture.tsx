import type { AxiosAdapter } from "axios";
import { useEffect, useState } from "react";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import apiClient from "@/lib/api/client";
import type { OwnerBoundRequestConfig } from "@/lib/api/request-owner";
import { AuthenticatedContent } from "@/features/auth/components/authenticated-content";
import { SessionLifecycle } from "@/providers/session-lifecycle";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { ManagerAdministrationPage } from "../components/manager-administration/manager-administration-page";

export const operationsActor: User = {
  id: "11111111-1111-4111-8111-111111111111", email: "operations-a@example.test",
  full_name: "Synthetic A", role: "super_admin", agency_id: null, is_active: true,
  created_at: "2026-10-01", updated_at: "2026-10-01", last_login_at: null,
};
export const replacementOperationsActor = { ...operationsActor, id: "22222222-2222-4222-8222-222222222222", email: "operations-b@example.test" };

/** Real page, hooks, API, owner adapter and session reset; final network only is synthetic. */
export function createOperationsAuthorityContext() {
  const gate = Promise.withResolvers<void>();
  const entered: unknown[] = [], settled: unknown[] = [];
  const mounts: string[] = [], unmounts: string[] = [];
  const writes: Array<{ path: string; actor: string; authority?: string; body: unknown }> = [];
  const previousAdapter = apiClient.defaults.adapter;
  const adapter: AxiosAdapter = async config => {
    if (config.url !== "/api/v1/admin/managers") throw new Error("Unexpected synthetic operations request: " + config.url);
    if (config.method === "post") writes.push({ path: config.url,
      actor: String(config.headers.get("X-Expected-Actor-Id")),
      authority: (config as OwnerBoundRequestConfig).expectedAuthorityKey,
      body: typeof config.data === "string" ? JSON.parse(config.data) : config.data });
    const data = config.method === "get" ? [] : {
      id: "synthetic-manager", full_name: "Synthetic Manager", email: "manager@example.test",
      role: "agency_manager", agency_id: null, is_active: true, created_at: "2026-10-01",
      last_login_at: null, created_groups: [], assigned_groups: [], credential_state: "invited",
      activation_token: "synthetic+token/test",
    };
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
    return <><output data-testid="operations-page-owner">{actor}</output><ManagerAdministrationPage /></>;
  }
  return {
    client, writes, entered, settled, mounts, unmounts, release: () => gate.resolve(),
    mount: () => render(<QueryClientProvider client={client}><SessionLifecycle queryClient={client} />
      <AuthenticatedContent><Page /></AuthenticatedContent></QueryClientProvider>),
    cleanup: () => { client.clear(); apiClient.defaults.adapter = previousAdapter; },
  };
}
