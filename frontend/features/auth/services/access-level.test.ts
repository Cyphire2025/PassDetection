import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { changeAccessLevel, synchronizeAccessLevel } from "./access-level";

const effects = vi.hoisted(() => ({ change: vi.fn(), me: vi.fn(), reset: vi.fn(), navigate: vi.fn() }));
vi.mock("../api/auth.api", () => ({ authApi: { changeAccessLevel: effects.change, getMe: effects.me } }));
vi.mock("./access-level-navigation", () => ({ navigateToAccessLevel: effects.navigate }));
vi.mock("./session-state", () => ({
  clearSensitiveBrowserState: effects.reset,
  prepareSensitiveBrowserStateForUser: vi.fn(),
}));

const owner: User = {
  id: "owner", email: "owner@example.test", full_name: "Owner", role: "super_admin",
  actual_role: "super_admin", can_switch_access_level: true, agency_id: null,
  is_active: true, last_login_at: null, created_at: "2026-09-11", updated_at: "2026-09-11",
};
const staff: User = { ...owner, role: "agency_staff", agency_id: "agency-1" };

describe("access level session reconciliation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    effects.reset.mockResolvedValue(undefined);
    useAuthStore.setState({
      user: owner, isAuthenticated: true, hasHydrated: true, restorationStatus: "authenticated",
      sessionVersion: 1, isChangingAccessLevel: false, accessLevelError: null,
    });
  });

  it("accepts the confirmed server state if the POST response was interrupted", async () => {
    effects.change.mockRejectedValue({ message: "Network interrupted" });
    effects.me.mockResolvedValue(staff);
    await changeAccessLevel("agency_staff", new QueryClient());
    expect(useAuthStore.getState().user).toEqual(staff);
    expect(effects.navigate).toHaveBeenCalledWith(staff);
    expect(useAuthStore.getState().accessLevelError).toBeNull();
  });

  it("keeps old protected content blocked when the resulting role cannot be confirmed", async () => {
    effects.change.mockResolvedValue(staff);
    effects.me.mockRejectedValue({ message: "Network interrupted" });
    await changeAccessLevel("agency_staff", new QueryClient());
    expect(useAuthStore.getState().isChangingAccessLevel).toBe(true);
    expect(useAuthStore.getState().accessLevelError).toBe("Network interrupted");
    expect(effects.navigate).not.toHaveBeenCalled();
  });

  it("ignores duplicate selections during the same change", async () => {
    effects.change.mockResolvedValue(staff);
    effects.me.mockResolvedValue(staff);
    const client = new QueryClient();
    await Promise.all([changeAccessLevel("agency_staff", client), changeAccessLevel("agency_manager", client)]);
    expect(effects.change).toHaveBeenCalledExactlyOnceWith("agency_staff");
  });

  it("reconciles another tab from the shared cookie without posting a role or signing out", async () => {
    effects.me.mockResolvedValue(staff);
    await synchronizeAccessLevel();
    expect(effects.change).not.toHaveBeenCalled();
    expect(effects.reset).toHaveBeenCalledExactlyOnceWith("access_level_changed", false);
    expect(effects.navigate).toHaveBeenCalledWith(staff);
    expect(useAuthStore.getState()).toMatchObject({ user: staff, isAuthenticated: true, isChangingAccessLevel: false });
  });

  it("does not overwrite a replacement session with an old /me reconciliation", async () => {
    let finish!: (user: User) => void;
    effects.me.mockImplementation(() => new Promise<User>((resolve) => { finish = resolve; }));
    const synchronization = synchronizeAccessLevel();
    await vi.waitFor(() => expect(effects.me).toHaveBeenCalledOnce());
    useAuthStore.getState().setSession({ ...staff, id: "other-owner" });
    finish(staff);
    await synchronization;
    expect(useAuthStore.getState().user?.id).toBe("other-owner");
    expect(effects.navigate).not.toHaveBeenCalled();
  });
});
