import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import { LoginSessionEntry } from "./login-session-entry";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("./auth-hydrator", () => ({ AuthHydrator: () => <span data-testid="restoration-worker" /> }));
vi.mock("./login-form", () => ({ LoginForm: ({ notice }: { notice?: string }) => <div>
  <h1>Sign in form</h1>{notice && <p>{notice}</p>}
</div> }));

function completeCheck(authenticated: boolean) {
  act(() => useAuthStore.setState(state => ({
    isAuthenticated: authenticated,
    restorationStatus: authenticated ? "authenticated" : "rejected",
    hasHydrated: true,
    sessionVersion: state.sessionVersion + 1,
  })));
}

describe("login session entry", () => {
  beforeEach(() => {
    replace.mockReset();
    useAuthStore.setState({
      user: null, isAuthenticated: false, hasHydrated: false,
      restorationStatus: "restoring", sessionVersion: 0,
    });
  });

  it("checks saved cookies before offering password or MFA login", () => {
    render(<LoginSessionEntry />);
    expect(screen.getByRole("status")).toHaveTextContent("Checking your saved session");
    expect(screen.getByTestId("restoration-worker")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign in form" })).not.toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("opens the requested workspace after this entry is verified", async () => {
    render(<LoginSessionEntry from="/passports/groups/example?view=docs" />);
    completeCheck(true);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/passports/groups/example?view=docs"));
    expect(screen.queryByTestId("restoration-worker")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Opening your workspace");
  });

  it("shows sign in after rejection and stops restoration from interrupting MFA", () => {
    render(<LoginSessionEntry notice="Password changed. Sign in again." />);
    completeCheck(false);
    expect(screen.getByRole("heading", { name: "Sign in form" })).toBeInTheDocument();
    expect(screen.getByText("Password changed. Sign in again.")).toBeInTheDocument();
    expect(screen.queryByTestId("restoration-worker")).not.toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("keeps a transient failure retryable and accepts a later successful check", async () => {
    const retry = vi.fn();
    window.addEventListener("auth:retry-restoration", retry);
    render(<LoginSessionEntry />);
    act(() => useAuthStore.getState().markTemporarilyUnavailable());
    expect(screen.getByRole("alert")).toHaveTextContent("checked once the connection is back");
    expect(screen.queryByRole("heading", { name: "Sign in form" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry connection" }));
    expect(retry).toHaveBeenCalledOnce();
    completeCheck(true);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    window.removeEventListener("auth:retry-restoration", retry);
  });

  it("does not treat an old in-memory user as a freshly verified session", async () => {
    useAuthStore.setState({ isAuthenticated: true, hasHydrated: true, restorationStatus: "authenticated", sessionVersion: 4 });
    render(<LoginSessionEntry />);
    expect(screen.getByRole("status")).toHaveTextContent("Checking your saved session");
    expect(replace).not.toHaveBeenCalled();
    completeCheck(true);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
  });

  it.each(["https://elsewhere.test", "//elsewhere.test", "/session-restore?from=/login", "/login"])("cannot restore into an external or looping destination: %s", async from => {
    render(<LoginSessionEntry from={from} />);
    completeCheck(true);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
  });
});
