import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { AccountSecurityPanel } from "./account-security-panel";

const api = vi.hoisted(() => ({
  changePassword: vi.fn(),
  regenerateMfaRecoveryCodes: vi.fn(),
}));

vi.mock("../api/auth.api", () => ({
  authApi: api,
}));

const privilegedUser: User = {
  id: "user-1",
  email: "admin@example.test",
  full_name: "Operations Admin",
  role: "agency_admin",
  agency_id: "agency-1",
  is_active: true,
  last_login_at: "2026-08-22T09:00:00Z",
  created_at: "2026-08-01T09:00:00Z",
  updated_at: "2026-08-22T09:00:00Z",
  credential_state: "active",
  mfa_required: true,
  mfa_enabled: true,
};

function renderPanel(mutationCache?: MutationCache) {
  const queryClient = new QueryClient({
    mutationCache,
    defaultOptions: { mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AccountSecurityPanel />
    </QueryClientProvider>,
  );
}

describe("AccountSecurityPanel", () => {
  const originalClearSession = useAuthStore.getState().clearSession;
  const clearSession = vi.fn();

  beforeEach(() => {
    api.changePassword.mockReset();
    api.regenerateMfaRecoveryCodes.mockReset();
    clearSession.mockReset();
    clearSession.mockResolvedValue(undefined);
    useAuthStore.setState({
      user: privilegedUser,
      isAuthenticated: true,
      hasHydrated: true,
      sessionVersion: 1,
      clearSession,
    });
  });

  afterEach(() => {
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      hasHydrated: false,
      sessionVersion: 0,
      clearSession: originalClearSession,
    });
  });

  it("validates password policy locally before sending a credential", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.type(screen.getByLabelText(/^Current password/), "ExistingPass1");
    await user.type(screen.getByLabelText(/^New password/), "weak");
    await user.type(screen.getByLabelText(/^Confirm new password/), "weak");
    await user.click(screen.getByRole("button", { name: "Change password" }));

    expect(screen.getByRole("alert")).toHaveTextContent(/at least 10 characters/i);
    expect(api.changePassword).not.toHaveBeenCalled();
  });

  it("changes the password then clears the local session without a duplicate revoke", async () => {
    api.changePassword.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderPanel();

    await user.type(screen.getByLabelText(/^Current password/), "ExistingPass1");
    await user.type(screen.getByLabelText(/^New password/), "ReplacementPass2");
    await user.type(screen.getByLabelText(/^Confirm new password/), "ReplacementPass2");
    await user.click(screen.getByRole("button", { name: "Change password" }));

    await waitFor(() => {
      expect(api.changePassword).toHaveBeenCalledWith("ExistingPass1", "ReplacementPass2");
      expect(clearSession).toHaveBeenCalledWith("logout", {
        revokeServerSession: false,
        loginReason: "password_changed",
      });
    });
  });

  it("shows newly regenerated recovery codes only after the protected request succeeds", async () => {
    const codes = ["AAAA-BBBB-CCCC-DDDD", "EEEE-FFFF-GGGG-HHHH"];
    api.regenerateMfaRecoveryCodes.mockResolvedValue(codes);
    const user = userEvent.setup();
    renderPanel();

    expect(screen.queryByText(codes[0])).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Regenerate recovery codes" }));

    expect(await screen.findByRole("status", { name: "New recovery codes" })).toBeInTheDocument();
    expect(screen.getByText(codes[0])).toBeInTheDocument();
    expect(screen.getByText(/displayed only in this response/i)).toBeInTheDocument();
  });

  it("removes A's recovery codes and password draft when the displayed account changes to B", async () => {
    const code = "OWNER-A-PRIVATE-RECOVERY";
    api.regenerateMfaRecoveryCodes.mockResolvedValue([code]);
    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByLabelText(/^Current password/), "OwnerAPrivateDraft1");
    await user.click(screen.getByRole("button", { name: "Regenerate recovery codes" }));
    expect(await screen.findByText(code)).toBeInTheDocument();
    act(() => useAuthStore.setState({ user: { ...privilegedUser, id: "owner-b" }, sessionVersion: 2 }));
    expect(screen.queryByText(code)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/^Current password/)).toHaveValue("");
  });

  it("does not sign out B when A's successful password response finishes later", async () => {
    let finish!: () => void;
    api.changePassword.mockImplementation(() => new Promise<void>((resolve) => { finish = resolve; }));
    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByLabelText(/^Current password/), "ExistingPass1");
    await user.type(screen.getByLabelText(/^New password/), "ReplacementPass2");
    await user.type(screen.getByLabelText(/^Confirm new password/), "ReplacementPass2");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    act(() => useAuthStore.setState({ user: { ...privilegedUser, id: "owner-b" }, sessionVersion: 2 }));
    await act(async () => finish());
    expect(clearSession).not.toHaveBeenCalled();
  });

  it("preserves the same-authority password draft across a session/profile renewal", async () => {
    const user = userEvent.setup();
    renderPanel();
    window.localStorage.setItem("passdetection:session-owner", privilegedUser.id);
    await user.type(screen.getByLabelText(/^Current password/), "CurrentPrivateDraft1");
    act(() => useAuthStore.getState().setSession({ ...privilegedUser, full_name: "Updated profile", updated_at: "2026-10-31" }));
    expect(screen.getByLabelText(/^Current password/)).toHaveValue("CurrentPrivateDraft1");
  });

  it("retains the password-change caller before global mutation preparation awaits", async () => {
    let release!: () => void;
    const entered = vi.fn();
    api.changePassword.mockResolvedValue(undefined);
    renderPanel(new MutationCache({ onMutate: async () => { entered(); await new Promise<void>((resolve) => { release = resolve; }); } }));
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/^Current password/), "ExistingPass1");
    await user.type(screen.getByLabelText(/^New password/), "ReplacementPass2");
    await user.type(screen.getByLabelText(/^Confirm new password/), "ReplacementPass2");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    await waitFor(() => expect(entered).toHaveBeenCalledOnce());
    act(() => useAuthStore.setState({ user: { ...privilegedUser, id: "owner-b" }, sessionVersion: 2 }));
    await act(async () => { release(); });
    await waitFor(() => expect(api.changePassword).not.toHaveBeenCalled());
    expect(clearSession).not.toHaveBeenCalled();
  });
});
