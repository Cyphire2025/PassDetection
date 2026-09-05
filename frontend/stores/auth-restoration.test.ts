import { beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "./auth.store";

vi.mock("@/features/auth/services/session-state", () => ({
  clearSensitiveBrowserState: vi.fn().mockResolvedValue(undefined),
  clearServerSessionCookies: vi.fn().mockResolvedValue(undefined),
  prepareSensitiveBrowserStateForUser: vi.fn(),
}));

beforeEach(() => {
  window.history.replaceState({}, "", "/login");
  useAuthStore.setState({
    user: null, isAuthenticated: false, hasHydrated: false,
    restorationStatus: "restoring", sessionVersion: 0,
  });
});

it("finishes rejected refresh restoration even before any user has been loaded", async () => {
  await useAuthStore.getState().clearSession("session_expired", { revokeServerSession: false });
  expect(useAuthStore.getState()).toMatchObject({
    user: null, isAuthenticated: false, hasHydrated: true,
    restorationStatus: "rejected", sessionVersion: 1,
  });
});
