
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { User, UserRole } from "@/types";
import { useAuthStore } from "@/stores/auth.store";
import { RouteCapabilityBoundary } from "./route-capability-boundary";

const navigation = vi.hoisted(() => ({
  pathname: "/audit-logs",
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ replace: navigation.replace }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={String(href)} {...props}>{children}</a>
  ),
}));

function user(role: UserRole): User {
  return {
    id: `${role}-id`,
    email: `${role}@example.test`,
    full_name: role,
    role,
    agency_id: role === "super_admin" ? null : "agency-1",
    is_active: true,
    last_login_at: null,
    created_at: "2026-08-23T00:00:00Z",
    updated_at: "2026-08-23T00:00:00Z",
  };
}

function setUser(nextUser: User) {
  useAuthStore.setState({
    user: nextUser,
    isAuthenticated: true,
    hasHydrated: true,
  });
}

describe("RouteCapabilityBoundary", () => {
  beforeEach(() => {
    navigation.pathname = "/audit-logs";
    navigation.replace.mockReset();
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      hasHydrated: true,
      sessionVersion: 0,
    });
  });

  it("does not mount privileged children before capability resolution succeeds", () => {
    const privilegedRequest = vi.fn();
    setUser(user("agency_manager"));

    render(
      <RouteCapabilityBoundary>
        <PrivilegedProbe onMount={privilegedRequest} />
      </RouteCapabilityBoundary>,
    );

    expect(privilegedRequest).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: /workspace is not available/i }))
      .toBeInTheDocument();
    expect(screen.queryByText("Privileged data")).not.toBeInTheDocument();
    expect(navigation.replace).toHaveBeenCalledWith("/dashboard");
  });

  it("mounts authorized content and removes it immediately after a role downgrade", () => {
    setUser(user("agency_admin"));
    render(
      <RouteCapabilityBoundary>
        <p>Privileged data</p>
      </RouteCapabilityBoundary>,
    );
    expect(screen.getByText("Privileged data")).toBeInTheDocument();

    act(() => setUser(user("agency_manager")));

    expect(screen.queryByText("Privileged data")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /workspace is not available/i }))
      .toBeInTheDocument();
  });

  it("shows an explicit fail-closed state for an unregistered deep link", () => {
    navigation.pathname = "/feature-owned-by-another-worktree";
    setUser(user("super_admin"));

    render(<RouteCapabilityBoundary><p>Unknown feature</p></RouteCapabilityBoundary>);

    expect(screen.queryByText("Unknown feature")).not.toBeInTheDocument();
    expect(screen.getByText(/not registered in the typed capability map/i)).toBeInTheDocument();
    expect(navigation.replace).not.toHaveBeenCalled();
  });
});

function PrivilegedProbe({ onMount }: { onMount: () => void }) {
  onMount();
  return <p>Privileged data</p>;
}
