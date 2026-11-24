import { Suspense, useEffect, useState } from "react";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { AxiosAdapter } from "axios";
import apiClient from "@/lib/api/client";
import type { OwnerBoundRequestConfig } from "@/lib/api/request-owner";
import { AuthenticatedContent } from "@/features/auth/components/authenticated-content";
import { SessionLifecycle } from "@/providers/session-lifecycle";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import type { MenuCategory, MenuWorkspace } from "../api/menu.api";
import { MenuPage } from "../components/menu-page";

export const menuActor: User = {
  id: "11111111-1111-4111-8111-111111111111", email: "menu-a@example.test", full_name: "Synthetic A",
  role: "agency_manager", agency_id: "33333333-3333-4333-8333-333333333333", is_active: true,
  created_at: "2026-10-01", updated_at: "2026-10-01", last_login_at: null,
};
export const nextMenuActor: User = { ...menuActor, id: "22222222-2222-4222-8222-222222222222", email: "menu-b@example.test" };
export function syntheticMenuWorkspace(): MenuWorkspace {
  return { categories: [], plans: [], total_dishes: 0, active_dishes: 0, max_trip_days_without_repeats: 0 };
}

/** Actual page/library/query/hooks/API/client owner adapter; only final network is synthetic. */
export function createMenuAuthorityContext() {
  const gate = Promise.withResolvers<void>();
  const entered: unknown[] = [], settled: unknown[] = [], mounts: string[] = [], unmounts: string[] = [];
  const workspaces = new Map<string, MenuWorkspace>();
  const writes: Array<{ actor: string; authority?: string; body: unknown }> = [];
  const previousAdapter = apiClient.defaults.adapter;
  const adapter: AxiosAdapter = async config => {
    const actor = useAuthStore.getState().user!.id;
    const workspace = workspaces.get(actor) ?? syntheticMenuWorkspace(); workspaces.set(actor, workspace);
    let data: MenuWorkspace | MenuCategory = workspace;
    if (config.method === "post" && config.url === "/api/v1/menu/categories") {
      const body = typeof config.data === "string" ? JSON.parse(config.data) : config.data;
      writes.push({ actor: String(config.headers.get("X-Expected-Actor-Id")),
        authority: (config as OwnerBoundRequestConfig).expectedAuthorityKey, body });
      const category: MenuCategory = { id: `synthetic-category-${actor}`, name: body.name, sort_order: 0,
        dish_count: 0, active_dish_count: 0, dishes: [], created_at: "2026-10-31", updated_at: "revision-1" };
      workspace.categories.push(category); data = category;
    } else if (config.method !== "get" || config.url !== "/api/v1/menu") {
      throw new Error("Unexpected synthetic menu request: " + config.url);
    }
    return { data, config, status: 200, statusText: "OK", headers: {} };
  };
  const client = new QueryClient({ mutationCache: new MutationCache({
    onMutate: async variables => { entered.push(variables); await gate.promise; },
    onSettled: (_data, error) => { settled.push(error); },
  }), defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
  apiClient.defaults.adapter = adapter;
  function Page() {
    const [actor] = useState(() => useAuthStore.getState().user!.id);
    useEffect(() => { mounts.push(actor); return () => { unmounts.push(actor); }; }, [actor]);
    return <><output data-testid="menu-page-owner">{actor}</output><Suspense fallback={<p>Loading synthetic page boundary</p>}><MenuPage /></Suspense></>;
  }
  return { client, writes, entered, settled, mounts, unmounts, release: () => gate.resolve(),
    mount: () => render(<QueryClientProvider client={client}><SessionLifecycle queryClient={client} />
      <AuthenticatedContent><Page /></AuthenticatedContent></QueryClientProvider>),
    cleanup: () => { client.clear(); apiClient.defaults.adapter = previousAdapter; },
  };
}
