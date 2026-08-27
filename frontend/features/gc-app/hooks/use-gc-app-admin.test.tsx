import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GcAppGroupControl } from "../types";
import { gcAppQueryKeys, useGcAppGroupMutations } from "./use-gc-app-admin";

const api = vi.hoisted(() => ({
  setMyPhotosEnabled: vi.fn(),
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

afterEach(() => {
  cleanup();
  api.setMyPhotosEnabled.mockReset();
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
    expect(api.setMyPhotosEnabled).toHaveBeenCalledWith(AGENCY_ID, CONTROL, true);
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
