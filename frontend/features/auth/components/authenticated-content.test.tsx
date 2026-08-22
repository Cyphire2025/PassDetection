import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthenticatedContent } from "./authenticated-content";
import { useAuthStore } from "@/stores/auth.store";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

describe("AuthenticatedContent", () => {
  beforeEach(() => {
    replace.mockReset();
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      hasHydrated: false,
      sessionVersion: 0,
    });
  });

  afterEach(() => {
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      hasHydrated: false,
      sessionVersion: 0,
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
});
