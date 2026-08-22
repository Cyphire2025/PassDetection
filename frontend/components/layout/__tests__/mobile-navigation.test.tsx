import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MobileNavigation } from "@/components/layout/mobile-navigation";
import { useAuthStore } from "@/stores/auth.store";

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
}));

vi.mock("next/link", () => ({
  default: ({ href, children, onClick, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a
      href={String(href)}
      onClick={(event) => {
        event.preventDefault();
        onClick?.(event);
      }}
      {...props}
    >
      {children}
    </a>
  ),
}));

vi.mock("@/components/brand/brand-logo", () => ({
  BrandLogo: () => <span>Global Connects</span>,
}));

const adminUser = {
  id: "user-1",
  email: "admin@example.test",
  full_name: "Agency Admin",
  role: "agency_admin" as const,
  agency_id: "agency-1",
  is_active: true,
  last_login_at: null,
  created_at: "2026-08-22T00:00:00Z",
  updated_at: "2026-08-22T00:00:00Z",
};

describe("MobileNavigation", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: adminUser,
      isAuthenticated: true,
      hasHydrated: true,
    });
  });

  it("traps focus, closes with Escape, and restores the trigger", async () => {
    const onClose = vi.fn();
    const { rerender } = render(
      <>
        <button data-mobile-navigation-trigger>Menu trigger</button>
        <MobileNavigation open onClose={onClose} />
      </>,
    );

    expect(screen.getByRole("dialog", { name: "Dashboard navigation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close navigation" })).toHaveFocus();

    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);

    rerender(
      <>
        <button data-mobile-navigation-trigger>Menu trigger</button>
        <MobileNavigation open={false} onClose={onClose} />
      </>,
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Menu trigger" })).toHaveFocus());
  });

  it("preserves role-filtered navigation and closes after a route is selected", async () => {
    const onClose = vi.fn();
    render(<MobileNavigation open onClose={onClose} />);

    expect(screen.getByRole("link", { name: "All Groups" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Old Data" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "All Groups" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("cycles keyboard focus within the modal boundary", async () => {
    render(<MobileNavigation open onClose={vi.fn()} />);
    const close = screen.getByRole("button", { name: "Close navigation" });
    const links = screen.getAllByRole("link");
    const lastLink = links.at(-1)!;

    lastLink.focus();
    await userEvent.tab();
    expect(close).toHaveFocus();

    close.focus();
    await userEvent.tab({ shift: true });
    expect(lastLink).toHaveFocus();
  });
});
