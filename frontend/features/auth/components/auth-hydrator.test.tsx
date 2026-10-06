import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { AuthHydrator } from "./auth-hydrator";

const { refresh, getMe } = vi.hoisted(() => ({ refresh: vi.fn(), getMe: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ refreshAuthenticatedSession: refresh }));
vi.mock("../api/auth.api", () => ({ authApi: { getMe } }));
vi.mock("../services/access-level", () => ({ synchronizeAccessLevel: vi.fn() }));
vi.mock("../services/session-state", () => ({
  prepareSensitiveBrowserStateForUser: vi.fn(),
  subscribeToSessionResets: () => () => undefined,
}));

const user: User = {
  id: "renewal-user", email: "renewal@example.test", full_name: "Renewal User",
  role: "agency_admin", agency_id: "renewal-agency", is_active: true,
  last_login_at: null, created_at: "2026-10-06", updated_at: "2026-10-06",
};

describe("AuthHydrator renewal scheduling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-06T12:00:00Z"));
    refresh.mockReset();
    getMe.mockReset().mockResolvedValue(user);
    useAuthStore.setState({
      user: null, isAuthenticated: false, hasHydrated: false,
      sessionVersion: 0, isChangingAccessLevel: false,
    });
  });

  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

  it("bounds a far-future expiry without repeatedly refreshing the session", async () => {
    refresh.mockResolvedValue({ user, access_token_expires_at: "2099-09-01T00:00:00Z" });
    const timers = vi.spyOn(window, "setTimeout");
    const view = render(<AuthHydrator />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(timers).toHaveBeenCalledWith(expect.any(Function), 2_147_483_647);
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("still renews a normal session two minutes before expiry", async () => {
    refresh.mockImplementation(async () => ({
      user, access_token_expires_at: new Date(Date.now() + 30 * 60_000).toISOString(),
    }));
    const view = render(<AuthHydrator />);
    await act(async () => { await vi.advanceTimersByTimeAsync(28 * 60_000 - 1); });
    expect(refresh).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(refresh).toHaveBeenCalledTimes(2);
    view.unmount();
  });
});
