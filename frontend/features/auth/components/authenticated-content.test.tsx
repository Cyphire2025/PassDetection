import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthenticatedContent } from "./authenticated-content";
import { useState } from "react";
import type { User } from "@/types";
import { installBrowserLocks } from "@/test-support/browser-locks";
import { useAuthStore } from "@/stores/auth.store";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

describe("AuthenticatedContent", () => {
  let locks: ReturnType<typeof installBrowserLocks>;
  beforeEach(() => {
    locks = installBrowserLocks();
    replace.mockReset();
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      hasHydrated: false,
      sessionVersion: 0,
      restorationStatus: "restoring",
      isChangingAccessLevel: false,
      accessLevelError: null,
    });
  });

  afterEach(() => {
    locks.restore();
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      hasHydrated: false,
      sessionVersion: 0,
      restorationStatus: "restoring",
      isChangingAccessLevel: false,
      accessLevelError: null,
    });
  });

  it("shows session restoration only while the initial check is pending", () => {
    render(<AuthenticatedContent>Protected workspace</AuthenticatedContent>);

    expect(screen.getByText(/restoring your secure session/i)).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("fails closed to login after hydration rejects the session", async () => {
    useAuthStore.setState({ hasHydrated: true, isAuthenticated: false });

    render(<AuthenticatedContent>Protected workspace</AuthenticatedContent>);

    await waitFor(() => {
      expect(replace).toHaveBeenCalledOnce();
    });
    expect(replace).toHaveBeenCalledWith("/login?reason=session_expired");
    expect(screen.queryByText("Protected workspace")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/returning to sign in/i);
  });

  it("mounts protected content only for an authenticated session", () => {
    useAuthStore.setState({ hasHydrated: true, isAuthenticated: true });

    render(<AuthenticatedContent>Protected workspace</AuthenticatedContent>);

    expect(screen.getByText("Protected workspace")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("keeps protected queries unmounted and allows retry after a transient outage", () => {
    useAuthStore.getState().markTemporarilyUnavailable();
    const retry = vi.fn();
    window.addEventListener("auth:retry-restoration", retry);
    render(<AuthenticatedContent>Protected workspace</AuthenticatedContent>);
    expect(screen.getByRole("alert")).toHaveTextContent("temporarily unavailable");
    expect(screen.queryByText("Protected workspace")).not.toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retry connection" }));
    expect(retry).toHaveBeenCalledOnce();
    window.removeEventListener("auth:retry-restoration", retry);
  });

  it("unmounts the previous role's protected content immediately during switching", () => {
    useAuthStore.setState({ hasHydrated: true, isAuthenticated: true });
    render(<AuthenticatedContent>Privileged workspace data</AuthenticatedContent>);
    act(() => useAuthStore.getState().beginAccessLevelChange());
    expect(screen.queryByText("Privileged workspace data")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Changing access level")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
    act(() => useAuthStore.getState().failAccessLevelChange("Connection interrupted"));
    expect(screen.getByRole("alert")).toHaveTextContent("Connection interrupted");
    expect(screen.getByRole("button", { name: "Reload to check access level" })).toBeInTheDocument();
    expect(screen.queryByText("Privileged workspace data")).not.toBeInTheDocument();
  });

  it("clears a private form draft across an account, effective role or agency change", () => {
    const user = { id: "owner-a", role: "agency_admin", agency_id: "agency-a" } as User;
    useAuthStore.setState({ user, hasHydrated: true, isAuthenticated: true });
    function PrivateDraft() {
      const [draft, setDraft] = useState("");
      return <input aria-label="Private draft" value={draft} onChange={(event) => setDraft(event.target.value)} />;
    }
    render(<AuthenticatedContent><PrivateDraft /></AuthenticatedContent>);
    for (const next of [{ ...user, id: "owner-b" }, { ...user, role: "agency_manager" as const }, { ...user, agency_id: "agency-b" }]) {
      fireEvent.change(screen.getByLabelText("Private draft"), { target: { value: "A private passenger draft" } });
      act(() => useAuthStore.setState({ user: next }));
      expect(screen.getByLabelText("Private draft")).toHaveValue("");
    }
  });

  it("preserves local drafts during renewal and same-authority profile revalidation", () => {
    const user = { id: "owner-a", role: "agency_admin", agency_id: "agency-a" } as User;
    useAuthStore.setState({ user, hasHydrated: true, isAuthenticated: true });
    function PrivateDraft() {
      const [draft, setDraft] = useState("");
      return <input aria-label="Private draft" value={draft} onChange={(event) => setDraft(event.target.value)} />;
    }
    render(<AuthenticatedContent><PrivateDraft /></AuthenticatedContent>);
    fireEvent.change(screen.getByLabelText("Private draft"), { target: { value: "Current passenger draft" } });
    act(() => useAuthStore.setState({ user: { ...user, full_name: "Updated profile" }, sessionVersion: 5 }));
    expect(screen.getByLabelText("Private draft")).toHaveValue("Current passenger draft");
  });

  it("explains how to recover when browser cookie coordination is unavailable", () => {
    locks.restore();
    useAuthStore.getState().markTemporarilyUnavailable();
    render(<AuthenticatedContent>Protected workspace</AuthenticatedContent>);
    expect(screen.getByRole("alert")).toHaveTextContent("Use HTTPS or localhost in a supported browser");
    expect(screen.getByRole("button", { name: "Retry connection" })).toBeInTheDocument();
    expect(screen.queryByText("Protected workspace")).not.toBeInTheDocument();
  });
});
