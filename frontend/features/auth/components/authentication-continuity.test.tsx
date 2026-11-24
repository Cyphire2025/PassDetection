import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { useLogin } from "../hooks/use-login";
import { ActivationForm } from "./activation-form";
import { PasswordRecoveryCompleteForm } from "./password-recovery-forms";
import { MfaChallengePanel } from "./login-form";

const api = vi.hoisted(() => ({ login: vi.fn(), activate: vi.fn(), completePasswordRecovery: vi.fn(), verifyMfa: vi.fn() }));
vi.mock("../api/auth.api", () => ({ authApi: api }));

const owner: User = {
  id: "owner-a", full_name: "Synthetic A", email: "a@example.test", role: "agency_admin", agency_id: "agency-a",
  is_active: true, last_login_at: null, created_at: "2026-01-01", updated_at: "2026-01-01",
};
const challenge = {
  status: "mfa_required" as const, challenge_token: "challenge-a", expires_at: "2099-01-01T00:00:00Z", setup_secret: null, otpauth_uri: null,
};

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false, gcTime: 0 } } })}>{children}</QueryClientProvider>;
}
function changeAccount() {
  useAuthStore.setState({ user: { ...owner, id: "owner-b" }, sessionVersion: 1, isAuthenticated: true });
}

describe("intentional identity operation continuity", () => {
  beforeEach(() => {
    Object.values(api).forEach((mock) => mock.mockReset());
    useAuthStore.setState({ user: null, sessionVersion: 0, isAuthenticated: false, isChangingAccessLevel: false });
    window.history.replaceState(null, "", "/login");
    // Legacy baselines may attempt jsdom navigation after overwriting B. The
    // assertions below establish the state error without printing that noise.
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });
  afterEach(() => { vi.restoreAllMocks(); window.history.replaceState(null, "", "/"); });

  it("does not replace B with a late successful password-login response for A", async () => {
    let finish!: (value: unknown) => void;
    api.login.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const hook = renderHook(useLogin, { wrapper });
    act(() => hook.result.current.mutate({ email: owner.email, password: "SyntheticPass1" }));
    await waitFor(() => expect(api.login).toHaveBeenCalledOnce());
    act(changeAccount);
    await act(async () => finish({ status: "authenticated", user: owner }));
    expect(useAuthStore.getState().user?.id).toBe("owner-b");
  });

  it.each(["activation", "recovery"])("does not replace B with a late successful %s response for A", async (operation) => {
    let finish!: (value: unknown) => void;
    const command = operation === "activation" ? api.activate : api.completePasswordRecovery;
    command.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    window.history.replaceState(null, "", `/${operation === "activation" ? "activate" : "recover"}?token=${"A".repeat(43)}`);
    render(operation === "activation" ? <ActivationForm /> : <PasswordRecoveryCompleteForm />, { wrapper });
    fireEvent.change(await screen.findByLabelText(/^New password/), { target: { value: "SyntheticPass1" } });
    fireEvent.change(screen.getByLabelText(/^Confirm password/), { target: { value: "SyntheticPass1" } });
    fireEvent.click(screen.getByRole("button", { name: operation === "activation" ? "Set password and continue" : "Reset password and continue" }));
    await waitFor(() => expect(command).toHaveBeenCalledOnce());
    act(changeAccount);
    await act(async () => finish({ status: "authenticated", user: owner }));
    expect(useAuthStore.getState().user?.id).toBe("owner-b");
  });

  it("does not replace B with a late MFA verification response for A", async () => {
    let finish!: (value: unknown) => void;
    api.verifyMfa.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    render(<MfaChallengePanel challenge={challenge} onBack={vi.fn()} />, { wrapper });
    fireEvent.change(screen.getByLabelText("Verification code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(api.verifyMfa).toHaveBeenCalledOnce());
    act(changeAccount);
    await act(async () => finish({ status: "authenticated", user: owner, recovery_codes: [] }));
    expect(useAuthStore.getState().user?.id).toBe("owner-b");
  });

  it("removes A's already-issued MFA recovery codes when account B becomes current", async () => {
    api.verifyMfa.mockResolvedValue({ status: "authenticated", user: owner, recovery_codes: ["OWNER-A-PRIVATE-RECOVERY"] });
    render(<MfaChallengePanel challenge={challenge} onBack={vi.fn()} />, { wrapper });
    fireEvent.change(screen.getByLabelText("Verification code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("OWNER-A-PRIVATE-RECOVERY")).toBeInTheDocument();
    act(changeAccount);
    expect(screen.queryByText("OWNER-A-PRIVATE-RECOVERY")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("account changed");
  });

  it.each(["activation", "recovery"])("hides a late %s enrollment secret after B becomes current", async (operation) => {
    let finish!: (value: unknown) => void;
    const command = operation === "activation" ? api.activate : api.completePasswordRecovery;
    command.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    window.history.replaceState(null, "", `/${operation === "activation" ? "activate" : "recover"}?token=${"A".repeat(43)}`);
    render(operation === "activation" ? <ActivationForm /> : <PasswordRecoveryCompleteForm />, { wrapper });
    fireEvent.change(await screen.findByLabelText(/^New password/), { target: { value: "SyntheticPass1" } });
    fireEvent.change(screen.getByLabelText(/^Confirm password/), { target: { value: "SyntheticPass1" } });
    fireEvent.click(screen.getByRole("button", { name: operation === "activation" ? "Set password and continue" : "Reset password and continue" }));
    await waitFor(() => expect(command).toHaveBeenCalledOnce());
    act(changeAccount);
    await act(async () => finish({ ...challenge, status: "mfa_enrollment_required", setup_secret: "OWNER-A-SETUP-SECRET" }));
    expect(screen.queryByText("OWNER-A-SETUP-SECRET")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("account changed");
  });

  it("rejects a previously rendered saved-codes action before React processes an account change", async () => {
    api.verifyMfa.mockResolvedValue({ status: "authenticated", user: owner, recovery_codes: ["OWNER-A-PRIVATE-RECOVERY"] });
    render(<MfaChallengePanel challenge={challenge} onBack={vi.fn()} />, { wrapper });
    fireEvent.change(screen.getByLabelText("Verification code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));
    const continueButton = await screen.findByRole("button", { name: "I saved these codes" });
    act(() => { changeAccount(); continueButton.click(); });
    expect(useAuthStore.getState().user?.id).toBe("owner-b");
  });

  it("rejects a stale rendered Verify action before dispatching A's challenge under B", async () => {
    api.verifyMfa.mockResolvedValue({ status: "authenticated", user: owner, recovery_codes: [] });
    render(<MfaChallengePanel challenge={challenge} onBack={vi.fn()} />, { wrapper });
    fireEvent.change(screen.getByLabelText("Verification code"), { target: { value: "123456" } });
    const verify = screen.getByRole("button", { name: "Verify" });
    await act(async () => { changeAccount(); verify.click(); });
    expect(api.verifyMfa).not.toHaveBeenCalled();
    expect(useAuthStore.getState().user?.id).toBe("owner-b");
  });

  it("rejects a login hook's old credential intent after its starting identity changes", async () => {
    api.login.mockResolvedValue({ status: "authenticated", user: owner });
    const hook = renderHook(useLogin, { wrapper });
    await act(async () => { changeAccount(); hook.result.current.mutate({ email: owner.email, password: "SyntheticPass1" }); });
    expect(api.login).not.toHaveBeenCalled();
    expect(useAuthStore.getState().user?.id).toBe("owner-b");
  });

  it.each(["activation", "recovery"])("rejects a stale rendered %s submit under B", async (operation) => {
    const command = operation === "activation" ? api.activate : api.completePasswordRecovery;
    command.mockResolvedValue({ status: "authenticated", user: owner });
    window.history.replaceState(null, "", `/${operation === "activation" ? "activate" : "recover"}?token=${"A".repeat(43)}`);
    render(operation === "activation" ? <ActivationForm /> : <PasswordRecoveryCompleteForm />, { wrapper });
    fireEvent.change(await screen.findByLabelText(/^New password/), { target: { value: "SyntheticPass1" } });
    fireEvent.change(screen.getByLabelText(/^Confirm password/), { target: { value: "SyntheticPass1" } });
    const submit = screen.getByRole("button", { name: operation === "activation" ? "Set password and continue" : "Reset password and continue" });
    await act(async () => { changeAccount(); submit.click(); });
    expect(command).not.toHaveBeenCalled();
    expect(useAuthStore.getState().user?.id).toBe("owner-b");
  });
});
