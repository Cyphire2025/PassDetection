import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { useMe } from "./use-me";

const getMe = vi.hoisted(() => vi.fn());
vi.mock("../api/auth.api", () => ({ authApi: { getMe } }));
const owner: User = {
  id: "same-owner", email: "owner@example.test", full_name: "Owner", role: "super_admin",
  actual_role: "super_admin", can_switch_access_level: true, agency_id: null,
  is_active: true, last_login_at: null, created_at: "2026-09-11", updated_at: "2026-09-11",
};

describe("useMe access level fencing", () => {
  beforeEach(() => {
    getMe.mockReset();
    useAuthStore.setState({
      user: owner, isAuthenticated: true, hasHydrated: true, sessionVersion: 1,
      isChangingAccessLevel: false, accessLevelError: null,
    });
  });

  it("does not restore an old superadmin role from a request started before switching", async () => {
    let finish!: (user: User) => void;
    getMe.mockImplementation(() => new Promise<User>((resolve) => { finish = resolve; }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    renderHook(useMe, { wrapper });
    await waitFor(() => expect(getMe).toHaveBeenCalledOnce());
    act(() => {
      useAuthStore.getState().beginAccessLevelChange();
      useAuthStore.getState().setSession({ ...owner, role: "agency_staff", agency_id: "agency-1" });
    });
    await act(async () => finish(owner));
    expect(useAuthStore.getState().user?.role).toBe("agency_staff");
    expect(getMe.mock.calls[0][0]).toBeInstanceOf(AbortSignal);
    client.clear();
  });
});
