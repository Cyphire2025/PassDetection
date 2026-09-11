import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { User, UserRole } from "@/types";
import { useAuthStore } from "@/stores/auth.store";
import { AccessLevelSwitcher, CoordinatorAccessLevelBar } from "./access-level-switcher";

const effects = vi.hoisted(() => ({ change: vi.fn(), me: vi.fn(), reset: vi.fn(), navigate: vi.fn() }));
vi.mock("../api/auth.api", () => ({ authApi: { changeAccessLevel: effects.change, getMe: effects.me } }));
vi.mock("../services/access-level-navigation", () => ({ navigateToAccessLevel: effects.navigate }));
vi.mock("../services/session-state", () => ({
  clearSensitiveBrowserState: effects.reset,
  prepareSensitiveBrowserStateForUser: vi.fn(),
}));

function account(role: UserRole = "super_admin", actualRole: UserRole = "super_admin"): User {
  return {
    id: "same-account", email: "owner@example.test", full_name: "SUPERADMIN",
    role, actual_role: actualRole, can_switch_access_level: actualRole === "super_admin",
    agency_id: role === "super_admin" ? null : "agency-1", access_level_agency_name: "Global Connect",
    is_active: true, last_login_at: null, created_at: "2026-09-11", updated_at: "2026-09-11",
  };
}

function mount(user = account(), coordinator = false) {
  useAuthStore.setState({ user });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["privileged-passports"], ["cached superadmin data"]);
  render(<QueryClientProvider client={client}>
    {coordinator ? <CoordinatorAccessLevelBar /> : <AccessLevelSwitcher />}
  </QueryClientProvider>);
  return client;
}

describe("superadmin access level menu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    effects.reset.mockResolvedValue(undefined);
    useAuthStore.setState({
      user: null, isAuthenticated: true, hasHydrated: true, restorationStatus: "authenticated",
      sessionVersion: 1, isChangingAccessLevel: false, accessLevelError: null,
      accessLevelAgencyChoice: null,
    });
  });

  it.each<UserRole>(["agency_admin", "agency_manager", "agency_staff", "agency_coordinator"])(
    "does not offer a selector to an actual %s account", (role) => {
      mount(account(role, role));
      expect(screen.queryByLabelText(/change access level/i)).not.toBeInTheDocument();
    },
  );

  it("requires the server's actual role and switch capability", () => {
    mount({ ...account(), actual_role: undefined, can_switch_access_level: false });
    expect(screen.queryByLabelText(/change access level/i)).not.toBeInTheDocument();
  });

  it("opens all four choices from the existing identity and closes with Escape", () => {
    mount();
    const trigger = screen.getByLabelText("Change access level, currently Superadmin");
    fireEvent.click(trigger);
    expect(screen.getByRole("group", { name: "Access levels" })).toBeVisible();
    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Superadmin", "Manager", "Staff", "Coordinator",
    ]);
    expect(screen.getByText("Global Connect")).toBeVisible();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(trigger.closest("details")).not.toHaveAttribute("open");
    expect(trigger).toHaveFocus();
  });

  it.each([
    ["Manager", "agency_manager"], ["Staff", "agency_staff"], ["Coordinator", "agency_coordinator"],
  ] as const)("changes to %s with one selection and clears the previous role's cache", async (label, role) => {
    const client = mount();
    const confirmed = account(role);
    effects.change.mockResolvedValue(confirmed);
    effects.me.mockResolvedValue(confirmed);
    fireEvent.click(screen.getByLabelText(/change access level/i));
    fireEvent.click(screen.getByRole("button", { name: label }));
    await waitFor(() => expect(effects.navigate).toHaveBeenCalledWith(confirmed));
    expect(effects.change).toHaveBeenCalledExactlyOnceWith(role);
    expect(effects.me).toHaveBeenCalledOnce();
    expect(effects.reset).toHaveBeenCalledWith("access_level_changed");
    expect(client.getQueryData(["privileged-passports"])).toBeUndefined();
    expect(useAuthStore.getState().user).toMatchObject({ id: "same-account", role });
  });

  it("keeps the return to Superadmin available in the coordinator layout", async () => {
    mount(account("agency_coordinator"), true);
    effects.change.mockResolvedValue(account());
    effects.me.mockResolvedValue(account());
    fireEvent.click(screen.getByLabelText("Change access level, currently Coordinator"));
    fireEvent.click(screen.getByRole("button", { name: "Superadmin" }));
    await waitFor(() => expect(effects.navigate).toHaveBeenCalledWith(account()));
    expect(effects.change).toHaveBeenCalledWith("super_admin");
  });

  it("shows the server error without pretending the denied change succeeded", async () => {
    mount();
    effects.change.mockRejectedValue({ message: "Select an agency before changing access level" });
    effects.me.mockResolvedValue(account());
    fireEvent.click(screen.getByLabelText(/change access level/i));
    fireEvent.click(screen.getByRole("button", { name: "Staff" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Select an agency"));
    expect(effects.navigate).not.toHaveBeenCalled();
    expect(useAuthStore.getState().user?.role).toBe("super_admin");
  });

  it("does not accept a late switch response after another session has replaced it", async () => {
    let finish!: (user: User) => void;
    effects.change.mockImplementation(() => new Promise<User>((resolve) => { finish = resolve; }));
    mount();
    fireEvent.click(screen.getByLabelText(/change access level/i));
    fireEvent.click(screen.getByRole("button", { name: "Staff" }));
    await waitFor(() => expect(effects.change).toHaveBeenCalledOnce());
    act(() => useAuthStore.getState().setSession({ ...account("agency_manager", "agency_manager"), id: "another-account" }));
    await act(async () => finish(account("agency_staff")));
    expect(useAuthStore.getState().user?.id).toBe("another-account");
    expect(effects.me).not.toHaveBeenCalled();
    expect(effects.navigate).not.toHaveBeenCalled();
  });

  it("offers an agency choice only when the server cannot infer the workspace", async () => {
    mount();
    effects.change.mockRejectedValueOnce({
      code: "ACCESS_LEVEL_AGENCY_REQUIRED", message: "Select an agency before changing access level",
      details: { agencies: [{ id: "agency-1", name: "Global Connect" }, { id: "agency-2", name: "Second Agency" }] },
    }).mockResolvedValueOnce(account("agency_staff"));
    effects.me.mockResolvedValueOnce(account()).mockResolvedValueOnce(account("agency_staff"));
    expect(screen.queryByLabelText("Agency workspace")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/change access level/i));
    fireEvent.click(screen.getByRole("button", { name: "Staff" }));
    await waitFor(() => expect(screen.getByLabelText("Agency workspace")).toBeVisible());
    fireEvent.change(screen.getByLabelText("Agency workspace"), { target: { value: "agency-1" } });
    await waitFor(() => expect(effects.navigate).toHaveBeenCalledWith(account("agency_staff")));
    expect(effects.change).toHaveBeenNthCalledWith(2, "agency_staff", "agency-1");
  });
});
