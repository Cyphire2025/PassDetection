import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { DEFAULT_PLATFORM_SETTINGS } from "../platform-settings-policy";
import { DELETE_CONFIRMATION, usePlatformDataPurge } from "./use-platform-data-purge";
import { usePlatformSettings } from "./use-platform-settings";

const client = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), delete: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: client }));
const saved = { ...DEFAULT_PLATFORM_SETTINGS, updated_at: "2026-10-06T12:00:00Z" };

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: { id: "synthetic-admin", role: "super_admin", agency_id: null } as User });
  client.get.mockResolvedValue({ data: saved });
});

describe("platform mutation admission", () => {
  it("admits only one policy save before React can render its pending state", async () => {
    let finish: (() => void) | undefined;
    client.put.mockImplementationOnce(() => new Promise((resolve) => { finish = () => resolve({ data: saved }); }));
    const { result } = renderHook(() => usePlatformSettings());
    await waitFor(() => expect(result.current.canEditPolicies).toBe(true));
    let pending: Promise<void>[] = [];
    act(() => { pending = [result.current.handleSave(), result.current.handleSave()]; });
    expect(client.put).toHaveBeenCalledTimes(1);
    expect(client.put).toHaveBeenCalledWith("/api/v1/admin/settings", expect.objectContaining({ expected_updated_at: saved.updated_at }));
    await act(async () => { finish?.(); await Promise.all(pending); });
    expect(result.current.saveMessage).toBe("Settings saved.");
  });

  it("admits one confirmed purge and allows an explicit retry after a failed request", async () => {
    let fail: (() => void) | undefined;
    client.delete.mockImplementationOnce(() => new Promise((_, reject) => { fail = () => reject(new Error("Synthetic failure")); }));
    const { result } = renderHook(() => usePlatformDataPurge(true));
    act(() => result.current.setConfirmation(DELETE_CONFIRMATION));
    let pending: Promise<void>[] = [];
    act(() => { pending = [result.current.handlePurgePassportData(), result.current.handlePurgePassportData()]; });
    expect(client.delete).toHaveBeenCalledTimes(1);
    await act(async () => { fail?.(); await Promise.all(pending); });
    expect(result.current.purgeError).toBe("Synthetic failure");
    expect(result.current.confirmation).toBe(DELETE_CONFIRMATION);
    client.delete.mockResolvedValueOnce({ data: { deleted_client_groups: 1 } });
    await act(async () => result.current.handlePurgePassportData());
    expect(client.delete).toHaveBeenCalledTimes(2);
    expect(result.current.confirmation).toBe("");
  });

  it("keeps purge requests blocked when current authority is unavailable", async () => {
    const { result } = renderHook(() => usePlatformDataPurge(false));
    act(() => result.current.setConfirmation(DELETE_CONFIRMATION));
    await act(async () => result.current.handlePurgePassportData());
    expect(client.delete).not.toHaveBeenCalled();
  });
});
