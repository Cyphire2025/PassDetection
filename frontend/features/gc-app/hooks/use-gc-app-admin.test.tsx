import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";

import type { GcAppGroupControl } from "../types";
import { gcAppQueryKeys, useGcAppGroupMutations } from "./use-gc-app-admin";

const api = vi.hoisted(() => ({
  setMyPhotosEnabled: vi.fn(),
  updateGroupControl: vi.fn(),
  createAnnouncement: vi.fn(),
  updateAnnouncement: vi.fn(),
  uploadCommonDocument: vi.fn(),
}));

vi.mock("../api/gc-app-admin.api", () => ({ gcAppAdminApi: api }));

const AGENCY_ID = "019d2a5b-6357-7600-8ed3-98c5ca70bfa1";
const CONTROL: GcAppGroupControl = {
  id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa2",
  name: "Singapore 2026",
  lifecycle: "active",
  destination: "Singapore",
  start_date: "2026-11-01",
  end_date: "2026-11-08",
  company: { id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa3", name: "Example Client" },
  gc_enabled: true,
  gc_revision: 7,
  gc_app_enabled: true,
  my_photos_enabled: false,
  passenger_access_enabled: true,
  client_manager_access_enabled: true,
  coordinator_access_enabled: true,
  access_starts_at: null,
  access_expires_at: null,
  access_revoked_at: null,
  revision: 7,
  organization_id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa3",
  active_mobile_users: 2,
  synced_device_count: 2,
  last_successful_sync_at: "2026-08-28T10:00:00Z",
  versions: {
    itinerary_version: 1,
    common_document_version: 2,
    announcement_version: 3,
  },
};

const actor = (id: string) => useAuthStore.setState({ user: { id, role: "agency_admin", agency_id: AGENCY_ID } as User });
beforeEach(() => actor("initial-actor"));
afterEach(() => {
  cleanup();
  Object.values(api).forEach((mock) => mock.mockReset());
});

describe("GC App operator save consistency", () => {
  it("never dispatches an old group mutation under a replacement actor after global onMutate pauses", async () => {
    let release!: () => void;
    const entered = vi.fn();
    const pause = new Promise<void>((resolve) => { release = resolve; });
    const queryClient = new QueryClient({ mutationCache: new MutationCache({ onMutate: async () => { entered(); await pause; } }) });
    api.updateGroupControl.mockResolvedValue({ ...CONTROL, revision: 8 });
    const { result } = renderHook(() => useGcAppGroupMutations(AGENCY_ID, CONTROL.id, 7), { wrapper: wrapper(queryClient) });
    let pending!: Promise<unknown>;
    act(() => { pending = result.current.updateControl.mutateAsync({ control: CONTROL, patch: { passenger_access_enabled: false } }); });
    const rejected = expect(pending).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    await waitFor(() => expect(entered).toHaveBeenCalledOnce());
    actor("replacement-actor");
    await act(async () => { release(); await rejected; });
    expect(api.updateGroupControl).not.toHaveBeenCalled();
    queryClient.clear();
  });
  it.each(["response", "cancel"])("does not repopulate private control cache when the actor changes during %s", async (phase) => {
    const queryClient = client();
    const key = gcAppQueryKeys.groupControl(AGENCY_ID, CONTROL.id);
    const changeActor = () => { actor("replacement-actor"); queryClient.clear(); };
    queryClient.setQueryData(key, CONTROL);
    api.updateGroupControl.mockImplementation(async () => {
      if (phase === "response") changeActor();
      return { ...CONTROL, revision: 8 };
    });
    vi.spyOn(queryClient, "cancelQueries").mockImplementation(async () => { if (phase === "cancel") changeActor(); });
    const { result } = renderHook(() => useGcAppGroupMutations(AGENCY_ID, CONTROL.id, 7), { wrapper: wrapper(queryClient) });
    await act(async () => {
      await expect(result.current.updateControl.mutateAsync({ control: CONTROL, patch: { passenger_access_enabled: false } }))
        .rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    });
    expect(queryClient.getQueryData(key)).toBeUndefined();
  });
  it.each(["announcement", "upload"])("does not write an old %s into a replacement account's content cache", async (kind) => {
    const queryClient = client();
    const key = gcAppQueryKeys.groupContent(AGENCY_ID, CONTROL.id);
    const replacementContent = { common_documents: [], announcements: [] };
    queryClient.setQueryData(key, { common_documents: [], announcements: [] });
    api.createAnnouncement.mockResolvedValue({ id: "old-private-announcement", is_published: true });
    api.uploadCommonDocument.mockResolvedValue({ id: "old-private-document", is_published: false });
    vi.spyOn(queryClient, "cancelQueries").mockImplementation(async () => {
      actor("replacement-actor"); queryClient.clear(); queryClient.setQueryData(key, replacementContent);
    });
    const { result } = renderHook(() => useGcAppGroupMutations(AGENCY_ID, CONTROL.id, 7), { wrapper: wrapper(queryClient) });
    await act(async () => {
      const pending = kind === "announcement"
        ? result.current.createAnnouncement.mutateAsync({ title: "Private", body: "Private", priority: "normal", available_from: null, available_until: null, publish: true })
        : result.current.uploadDocument.mutateAsync({ file: new File(["synthetic"], "synthetic.pdf"), title: "Private", category: "itinerary_pdf" });
      await expect(pending).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    });
    expect(queryClient.getQueryData(key)).toEqual(replacementContent);
  });
  it("updates access immediately from the response even if background refresh fails", async () => {
    const queryClient = client();
    const key = gcAppQueryKeys.groupControl(AGENCY_ID, CONTROL.id);
    queryClient.setQueryData(key, CONTROL);
    vi.spyOn(queryClient, "invalidateQueries").mockRejectedValue(new Error("offline refresh"));
    api.updateGroupControl.mockResolvedValue({ ...CONTROL, passenger_access_enabled: false, revision: 8 });
    const { result } = renderHook(() => useGcAppGroupMutations(AGENCY_ID, CONTROL.id, 7), { wrapper: wrapper(queryClient) });
    await act(async () => {
      await result.current.updateControl.mutateAsync({ control: CONTROL, patch: { passenger_access_enabled: false } });
    });
    expect(queryClient.getQueryData(key)).toMatchObject({ passenger_access_enabled: false, revision: 8 });
    expect(api.updateGroupControl).toHaveBeenCalledTimes(1);
  });

  it("does not move a newer confirmed access revision backwards", async () => {
    const queryClient = client();
    const key = gcAppQueryKeys.groupControl(AGENCY_ID, CONTROL.id);
    queryClient.setQueryData(key, { ...CONTROL, revision: 10 });
    api.updateGroupControl.mockResolvedValue({ ...CONTROL, revision: 8 });
    const { result } = renderHook(() => useGcAppGroupMutations(AGENCY_ID, CONTROL.id, 7), { wrapper: wrapper(queryClient) });
    await act(async () => { await result.current.updateControl.mutateAsync({ control: CONTROL, patch: {} }); });
    expect(queryClient.getQueryData(key)).toMatchObject({ revision: 10 });
  });

  it("reconciles content and revision after an uncertain save without automatically resending", async () => {
    const queryClient = client();
    const invalidations = vi.spyOn(queryClient, "invalidateQueries");
    api.createAnnouncement.mockRejectedValue(new Error("response lost"));
    const { result } = renderHook(() => useGcAppGroupMutations(AGENCY_ID, CONTROL.id, 7), { wrapper: wrapper(queryClient) });
    await act(async () => {
      await expect(result.current.createAnnouncement.mutateAsync({
        title: "Test", body: "Test", priority: "normal", available_from: null, available_until: null, publish: true,
      })).rejects.toThrow("response lost");
    });
    expect(api.createAnnouncement).toHaveBeenCalledTimes(1);
    expect(invalidations).toHaveBeenCalledWith({ queryKey: gcAppQueryKeys.groupContent(AGENCY_ID, CONTROL.id) });
    expect(invalidations).toHaveBeenCalledWith({ queryKey: gcAppQueryKeys.groupControl(AGENCY_ID, CONTROL.id) });
  });

  it("keeps the published document visible while its replacement is still a draft", async () => {
    const queryClient = client();
    const key = gcAppQueryKeys.groupContent(AGENCY_ID, CONTROL.id);
    const published = { id: "old", title: "Itinerary", is_published: true };
    const draft = { id: "new", title: "Itinerary", is_published: false };
    queryClient.setQueryData(key, { common_documents: [published], announcements: [] });
    api.uploadCommonDocument.mockResolvedValue(draft);
    const { result } = renderHook(() => useGcAppGroupMutations(AGENCY_ID, CONTROL.id, 7), { wrapper: wrapper(queryClient) });
    await act(async () => {
      await result.current.uploadDocument.mutateAsync({ file: new File(["test"], "test.pdf", { type: "application/pdf" }), title: "Itinerary", category: "itinerary_pdf", replace_document_id: "old" });
    });
    expect(queryClient.getQueryData(key)).toMatchObject({ common_documents: [draft, published] });
  });
});

describe("useGcAppGroupMutations My Photos control", () => {
  it("publishes only the canonical server response into the control cache", async () => {
    const queryClient = client();
    const controlKey = gcAppQueryKeys.groupControl(AGENCY_ID, CONTROL.id);
    const updated = { ...CONTROL, my_photos_enabled: true, revision: 8 };
    queryClient.setQueryData(controlKey, CONTROL);
    api.setMyPhotosEnabled.mockResolvedValue(updated);
    const { result } = renderHook(
      () => useGcAppGroupMutations(AGENCY_ID, CONTROL.id, CONTROL.revision),
      { wrapper: wrapper(queryClient) },
    );

    await act(async () => {
      await result.current.setMyPhotosEnabled.mutateAsync({ control: CONTROL, enabled: true });
    });

    expect(api.setMyPhotosEnabled).toHaveBeenCalledTimes(1);
    expect(api.setMyPhotosEnabled).toHaveBeenCalledWith(AGENCY_ID, CONTROL, true, {
      expectedOwnerUserId: "initial-actor",
      expectedAuthorityKey: JSON.stringify(["initial-actor", "agency_admin", AGENCY_ID]),
    });
    expect(queryClient.getQueryData(controlKey)).toEqual(updated);
  });

  it("keeps the prior canonical state and invalidates it after a revision conflict", async () => {
    const queryClient = client();
    const controlKey = gcAppQueryKeys.groupControl(AGENCY_ID, CONTROL.id);
    queryClient.setQueryData(controlKey, CONTROL);
    const invalidations = vi.spyOn(queryClient, "invalidateQueries");
    api.setMyPhotosEnabled.mockRejectedValue({
      code: "HTTP_409",
      status: 409,
      message: "GC App settings changed; refresh and retry",
    });
    const { result } = renderHook(
      () => useGcAppGroupMutations(AGENCY_ID, CONTROL.id, CONTROL.revision),
      { wrapper: wrapper(queryClient) },
    );

    await act(async () => {
      await expect(result.current.setMyPhotosEnabled.mutateAsync({
        control: CONTROL,
        enabled: true,
      })).rejects.toMatchObject({ status: 409 });
    });

    expect(api.setMyPhotosEnabled).toHaveBeenCalledTimes(1);
    expect(queryClient.getQueryData(controlKey)).toEqual(CONTROL);
    await waitFor(() => {
      expect(invalidations).toHaveBeenCalledWith({ queryKey: controlKey });
    });
  });
});

function client() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function wrapper(queryClient: QueryClient) {
  return function QueryWrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}
