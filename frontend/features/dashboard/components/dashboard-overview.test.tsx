import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { DashboardOverview } from "./dashboard-overview";

const stats = vi.hoisted(() => ({ use: vi.fn(), refetch: vi.fn() }));
vi.mock("../hooks/use-dashboard-stats", () => ({ useDashboardStats: stats.use }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ prefetch: vi.fn() }) }));
const initialAuth = useAuthStore.getState();
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: { id: "dashboard-actor", role: "agency_admin", agency_id: "agency" } as User });
});
afterEach(() => { cleanup(); useAuthStore.setState(initialAuth); });

describe("Dashboard statistics availability", () => {
  it("does not present a failed initial load as zero records or an empty intake", async () => {
    stats.use.mockReturnValue({ data: undefined, isLoading: false, isFetching: false, error: new Error("unavailable"), refetch: stats.refetch });
    render(<DashboardOverview />);
    expect(screen.queryByText("No recent passport intake")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Passport operations summary")).not.toHaveTextContent(/\b0\b/);
    expect(screen.getByText("Recent activity unavailable")).toBeVisible();
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry statistics" }));
    expect(stats.refetch).toHaveBeenCalledOnce();
  });

  it("keeps the last known values and passenger rows when a refresh fails", () => {
    stats.use.mockReturnValue({ data: { total_passports: 47, pending_review: 2, confirmed: 45, active_links: 3,
      recent_submissions: [{ id: "passport", client_name: "Synthetic Traveller", client_email: "traveller@example.test", status: "client_submitted", created_at: "2026-10-30T00:00:00Z" }] },
    isLoading: false, isFetching: false, error: new Error("refresh failed"), refetch: stats.refetch });
    render(<DashboardOverview />);
    expect(screen.getByLabelText("Passport operations summary")).toHaveTextContent("47");
    expect(screen.getAllByText("Synthetic Traveller")).toHaveLength(2);
    expect(screen.getByRole("alert")).toHaveTextContent("last available statistics");
  });

  it("shows zero and empty intake when the server successfully returns an empty result", () => {
    stats.use.mockReturnValue({ data: { total_passports: 0, pending_review: 0, confirmed: 0, active_links: 0, recent_submissions: [] }, isLoading: false, error: null, refetch: stats.refetch });
    render(<DashboardOverview />);
    expect(screen.getByText("No recent passport intake")).toBeVisible();
    expect(screen.getByLabelText("Passport operations summary")).toHaveTextContent("0");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
