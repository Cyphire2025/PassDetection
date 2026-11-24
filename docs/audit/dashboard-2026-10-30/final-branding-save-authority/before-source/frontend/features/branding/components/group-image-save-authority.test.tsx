import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { AxiosAdapter } from "axios";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import type { OwnerBoundRequestConfig } from "@/lib/api/request-owner";
import { AuthenticatedContent } from "@/features/auth/components/authenticated-content";
import { SessionLifecycle } from "@/providers/session-lifecycle";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { GroupImageDialog } from "./group-image-dialog";

const crop = vi.hoisted(() => vi.fn());
vi.mock("../image-crop", async original => ({
  ...await original<typeof import("../image-crop")>(), cropBrandingImage: crop,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

const initialActor: User = {
  id: "branding-actor-a", agency_id: "branding-agency", role: "agency_admin",
  email: "a@example.test", full_name: "Synthetic A", is_active: true,
  created_at: "2026-10-01", updated_at: "2026-10-01", last_login_at: null,
};
const replacementActor = { ...initialActor, id: "branding-actor-b", email: "b@example.test" };
const currentUrl = "/api/v1/branding/group-banner/synthetic-group?v=original";

function deferred<T>() {
  let resolve!: (value: T) => void;
  return { promise: new Promise<T>(done => { resolve = done; }), resolve: (value: T) => resolve(value) };
}

const contexts: Array<ReturnType<typeof setup>> = [];
const previousAdapter = apiClient.defaults.adapter;

beforeEach(() => {
  crop.mockReset();
  useAuthStore.setState({
    user: null, isAuthenticated: false, hasHydrated: false, sessionVersion: 0,
    restorationStatus: "restoring", isChangingAccessLevel: false, accessLevelError: null,
  });
  useAuthStore.getState().setSession(initialActor);
});
afterEach(() => {
  cleanup();
  for (const context of contexts.splice(0)) context.client.clear();
  apiClient.defaults.adapter = previousAdapter;
  useAuthStore.setState({ user: null, isAuthenticated: false, hasHydrated: false });
});

function setup() {
  const gate = deferred<File>();
  crop.mockReturnValue(gate.promise);
  const writes: Array<{ actor: unknown; authority: unknown; url: string; version: unknown; filename: string; parts: string[] }> = [];
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const closed = vi.fn(), mounts: string[] = [], unmounts: string[] = [];
  const adapter: AxiosAdapter = async config => {
    if (config.method !== "put" || config.url !== "/api/v1/branding/group-banner/synthetic-group") {
      throw new Error("Unexpected synthetic branding request");
    }
    const body = config.data as FormData;
    writes.push({
      actor: config.headers.get("X-Expected-Actor-Id"),
      authority: (config as OwnerBoundRequestConfig).expectedAuthorityKey,
      url: config.url, version: body.get("expected_version"),
      filename: (body.get("file") as File).name, parts: Array.from(body.keys()),
    });
    return { data: { url: "/api/v1/branding/group-banner/synthetic-group?v=new", revision: null }, status: 200, statusText: "OK", headers: {}, config };
  };
  // Keep the actual synchronous owner capture, cookie wrapper, owner-bound
  // adapter and response guards; only the final network delegate is synthetic.
  apiClient.defaults.adapter = adapter;
  function Workspace() {
    const [owner] = useState(() => useAuthStore.getState().user!.id);
    useEffect(() => {
      mounts.push(owner);
      return () => { unmounts.push(owner); };
    }, [owner]);
    return <>
      <output data-testid="branding-owner">{owner}</output>
      <GroupImageDialog kind="banner" groupId="synthetic-group" currentUrl={currentUrl} onClose={closed} />
    </>;
  }
  const view = render(<QueryClientProvider client={client}>
    <SessionLifecycle queryClient={client} />
    <AuthenticatedContent><Workspace /></AuthenticatedContent>
  </QueryClientProvider>);
  const context = { gate, writes, client, invalidate, closed, mounts, unmounts, view };
  contexts.push(context);
  return context;
}

function startAdjustedSave() {
  fireEvent.change(screen.getByRole("slider", { name: "Horizontal position" }), { target: { value: "30" } });
  fireEvent.click(screen.getByRole("button", { name: "Save banner" }));
}
async function finishCrop(context: ReturnType<typeof setup>) {
  await act(async () => { context.gate.resolve(new File(["synthetic pixels"], "synthetic-crop.jpg", { type: "image/jpeg" })); });
}

it.each([
  ["account", replacementActor],
  ["role", { ...initialActor, role: "agency_manager" as const }],
  ["agency", { ...initialActor, agency_id: "replacement-agency" }],
])("does not dispatch an old image intent after a deferred crop crosses %s authority", async (_name, actor) => {
  const context = setup();
  startAdjustedSave();
  expect(crop).toHaveBeenCalledTimes(1);
  act(() => useAuthStore.getState().setSession(actor));
  expect(context.unmounts).toEqual([initialActor.id]);
  context.invalidate.mockClear();
  await finishCrop(context);
  expect(context.writes).toEqual([]);
  expect(context.invalidate).not.toHaveBeenCalled();
  expect(context.closed).not.toHaveBeenCalled();
});

it.each([false, true])("preserves the same-owner save body, original version and cache callbacks with profile refresh=%s", async profile => {
  const context = setup();
  startAdjustedSave();
  if (profile) act(() => useAuthStore.getState().setSession({ ...initialActor, full_name: "Updated synthetic profile", updated_at: "2026-11-01" }));
  await finishCrop(context);
  await waitFor(() => expect(context.closed).toHaveBeenCalledTimes(1));
  expect(context.writes).toEqual([{
    actor: initialActor.id, authority: JSON.stringify([initialActor.id, initialActor.role, initialActor.agency_id]),
    url: "/api/v1/branding/group-banner/synthetic-group", version: "original", filename: "synthetic-crop.jpg", parts: ["file", "expected_version"],
  }]);
  expect(context.invalidate.mock.calls.map(([options]) => options?.queryKey)).toEqual([["companies"], ["passports"], ["upload-links"], ["document-distribution"]]);
  expect(context.unmounts).toEqual([]);
});
