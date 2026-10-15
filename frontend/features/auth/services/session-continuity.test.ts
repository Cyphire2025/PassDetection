import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";

vi.mock("./session-state", () => ({ prepareSensitiveBrowserStateForUser: vi.fn() }));

const user: User = { id: "synthetic-user", email: "staff@example.invalid", full_name: "Synthetic Staff",
  role: "agency_admin", agency_id: "company-workspace", is_active: true, last_login_at: "2026-10-01",
  created_at: "2026-09-01", updated_at: "2026-10-01", capabilities: ["groups", "documents"] };

beforeEach(() => useAuthStore.setState({ user, isAuthenticated: true, hasHydrated: true,
  restorationStatus: "authenticated", sessionVersion: 7, isChangingAccessLevel: false }));

describe("explicit existing-session revalidation", () => {
  it("preserves cache identity only for the unchanged authenticated context", () => {
    expect(useAuthStore.getState().applySessionRevalidation({ ...user, full_name: "Updated display", capabilities: ["documents", "groups"] }, 7)).toBe(true);
    expect(useAuthStore.getState().sessionVersion).toBe(7);
    expect(useAuthStore.getState().user?.full_name).toBe("Updated display");
    // A normal login remains a new boundary, even to the same account.
    useAuthStore.getState().setSession(user);
    expect(useAuthStore.getState().sessionVersion).toBe(8);
  });

  it.each<Partial<User>>([
    { id: "another-user" }, { agency_id: "another-workspace" }, { role: "agency_staff" },
    { actual_role: "super_admin" }, { capabilities: ["groups"] }, { is_active: false },
    { credential_state: "invited" }, { mfa_required: true }, { mfa_enabled: true },
    { can_switch_access_level: true }, { updated_at: "2026-10-02" }, { last_login_at: "2026-10-02" },
  ])("invalidates cached authority after a confirmed context change: %j", (change) => {
    useAuthStore.getState().applySessionRevalidation({ ...user, ...change }, 7);
    expect(useAuthStore.getState().sessionVersion).toBe(8);
  });

  it("ignores a late response after logout/access transitions and hydrates a new session", () => {
    useAuthStore.setState({ user: null, isAuthenticated: false, sessionVersion: 8 });
    expect(useAuthStore.getState().applySessionRevalidation(user, 7)).toBe(false);
    expect(useAuthStore.getState().user).toBeNull();
    useAuthStore.setState({ isChangingAccessLevel: true });
    expect(useAuthStore.getState().applySessionRevalidation(user, 8)).toBe(false);
    useAuthStore.setState({ isChangingAccessLevel: false, hasHydrated: false });
    expect(useAuthStore.getState().applySessionRevalidation(user, 8)).toBe(true);
    expect(useAuthStore.getState().sessionVersion).toBe(9);
  });
});
