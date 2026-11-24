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
import { saveBrandingImage } from "../api/branding-images.api";

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

const clients: QueryClient[] = [];
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
  for (const client of clients.splice(0)) client.clear();
  apiClient.defaults.adapter = previousAdapter;
  useAuthStore.setState({ user: null, isAuthenticated: false, hasHydrated: false });
});

function setup(holdResponse = false) {
  const gate = deferred<File>();
  const response = deferred<void>();
  crop.mockReturnValue(gate.promise);
  const writes: Array<{ actor: unknown; authority: unknown; url: string; version: unknown; filename: string; parts: string[] }> = [];
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const closed = vi.fn(), mounts: string[] = [], unmounts: string[] = [];
  const signals: Array<AbortSignal | undefined> = [];
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
    signals.push(config.signal as AbortSignal | undefined);
    if (holdResponse) await response.promise;
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
  const context = { gate, writes, signals, client, invalidate, closed, mounts, unmounts, view, releaseResponse: () => response.resolve(undefined) };
  clients.push(client);
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

it("does not revive an old save after an account leaves and returns while cropping", async () => {
  const context = setup();
  startAdjustedSave();
  act(() => useAuthStore.getState().setSession(replacementActor));
  act(() => useAuthStore.getState().setSession(initialActor));
  expect(context.mounts).toEqual([initialActor.id, replacementActor.id, initialActor.id]);
  context.invalidate.mockClear();
  await finishCrop(context);
  expect(context.writes).toEqual([]);
  expect(context.invalidate).not.toHaveBeenCalled();
  expect(context.closed).not.toHaveBeenCalled();
});

it("does not dispatch a deferred crop after a normal same-owner route unmount", async () => {
  const context = setup();
  startAdjustedSave();
  context.view.unmount();
  await finishCrop(context);
  expect(context.writes).toEqual([]);
  expect(context.invalidate).not.toHaveBeenCalled();
  expect(context.closed).not.toHaveBeenCalled();
});

it.each(["unmount", "account round-trip"])("cancels before the real delegate after an async interceptor crosses %s", async transition => {
  const entered = deferred<void>(), resume = deferred<void>();
  const interceptor = apiClient.interceptors.request.use(async config => {
    entered.resolve(undefined);
    await resume.promise;
    return config;
  });
  try {
    const context = setup();
    startAdjustedSave();
    await finishCrop(context);
    await entered.promise;
    if (transition === "unmount") context.view.unmount();
    else {
      act(() => useAuthStore.getState().setSession(replacementActor));
      act(() => useAuthStore.getState().setSession(initialActor));
    }
    context.invalidate.mockClear();
    await act(async () => { resume.resolve(undefined); });
    expect(context.writes).toEqual([]);
    expect(context.invalidate).not.toHaveBeenCalled();
    expect(context.closed).not.toHaveBeenCalled();
  } finally {
    apiClient.interceptors.request.eject(interceptor);
    resume.resolve(undefined);
  }
});

it("ignores an already-dispatched response after unmount and aborts its caller signal", async () => {
  const context = setup(true);
  startAdjustedSave();
  await finishCrop(context);
  await waitFor(() => expect(context.writes).toHaveLength(1));
  context.view.unmount();
  expect(context.signals[0]?.aborted).toBe(true);
  await act(async () => { context.releaseResponse(); });
  expect(context.writes).toHaveLength(1);
  expect(context.invalidate).not.toHaveBeenCalled();
  expect(context.closed).not.toHaveBeenCalled();
});

it("passes the initiating full authority through the real asynchronous API interceptor chain", async () => {
  const context = setup();
  const entered = deferred<void>(), resume = deferred<void>();
  const interceptor = apiClient.interceptors.request.use(async config => {
    entered.resolve(undefined);
    await resume.promise;
    return config;
  });
  try {
    const promise = saveBrandingImage("group-banner", "synthetic-group", undefined,
      new File(["synthetic"], "direct.jpg"), currentUrl, initialActor.id,
      { expectedAuthorityKey: JSON.stringify([initialActor.id, initialActor.role, initialActor.agency_id]) });
    const rejected = expect(promise).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    await entered.promise;
    act(() => useAuthStore.getState().setSession({ ...initialActor, role: "agency_manager" }));
    resume.resolve(undefined);
    await rejected;
    expect(context.writes).toEqual([]);
  } finally {
    apiClient.interceptors.request.eject(interceptor);
    resume.resolve(undefined);
  }
});

it("fails closed without an initiating owner before crop or HTTP dispatch", async () => {
  const context = setup();
  context.view.rerender(<QueryClientProvider client={context.client}>
    <GroupImageDialog kind="banner" groupId="synthetic-group" currentUrl={currentUrl} onClose={context.closed} />
  </QueryClientProvider>);
  act(() => useAuthStore.setState({ user: null, isAuthenticated: false }));
  startAdjustedSave();
  expect(crop).not.toHaveBeenCalled();
  expect(context.writes).toEqual([]);
  expect(screen.getByRole("alert")).toHaveTextContent("signed-in account changed");
});

it.each(["default", "legacy six-argument"])("preserves the %s API caller's upload body and current authority", async mode => {
  const context = setup();
  const file = new File(["synthetic"], "direct.jpg", { type: "image/jpeg" });
  if (mode === "default") await saveBrandingImage("group-banner", "synthetic-group", undefined, file, currentUrl);
  else await saveBrandingImage("group-banner", "synthetic-group", undefined, file, currentUrl, initialActor.id);
  expect(context.writes).toEqual([{
    actor: initialActor.id, authority: JSON.stringify([initialActor.id, initialActor.role, initialActor.agency_id]),
    url: "/api/v1/branding/group-banner/synthetic-group", version: "original", filename: "direct.jpg", parts: ["file", "expected_version"],
  }]);
  expect(crop).not.toHaveBeenCalled();
});

it("captures legacy six-argument caller authority before asynchronous interceptors", async () => {
  const context = setup();
  const entered = deferred<void>(), resume = deferred<void>();
  const interceptor = apiClient.interceptors.request.use(async config => {
    entered.resolve(undefined);
    await resume.promise;
    return config;
  });
  try {
    const promise = saveBrandingImage("group-banner", "synthetic-group", undefined,
      new File(["synthetic"], "direct.jpg"), currentUrl, initialActor.id);
    const rejected = expect(promise).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    await entered.promise;
    act(() => useAuthStore.getState().setSession({ ...initialActor, role: "agency_manager" }));
    resume.resolve(undefined);
    await rejected;
    expect(context.writes).toEqual([]);
  } finally {
    apiClient.interceptors.request.eject(interceptor);
    resume.resolve(undefined);
  }
});
