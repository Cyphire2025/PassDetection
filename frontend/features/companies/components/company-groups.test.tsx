import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { companiesApi } from "../api/companies.api";
import { CompanyGroups } from "./company-groups";

vi.mock("../api/companies.api", () => ({ companiesApi: { groups: vi.fn() } }));
const user: User = { id: "owner", role: "agency_admin", agency_id: "agency", full_name: "Owner", email: "owner@example.test", is_active: true, last_login_at: null, created_at: "2026-01-01", updated_at: "2026-01-01" };
const group = { id: "trip", name: "Japan Autumn", destination: "Japan", travel_date: "2026-11-01", return_date: "2026-11-08", status: "archived" as const, import_only: true, submission_count: 700 };
beforeEach(() => { vi.resetAllMocks(); useAuthStore.setState({ user, sessionVersion: 1, isChangingAccessLevel: false }); });
function mount() {
  return render(<QueryClientProvider client={new QueryClient()}><CompanyGroups agencyId="agency" companyId="company" /></QueryClientProvider>);
}

describe("company group sections", () => {
  it("uses server phases independently of group lifecycle and links View to the existing group page", async () => {
    vi.mocked(companiesApi.groups).mockImplementation(async (_agency, _company, params) => ({ items: params.phase === "active" ? [group] : [], next_cursor: null, has_more: false }));
    mount();
    const active = screen.getByRole("region", { name: "Active groups" });
    expect(await within(active).findByRole("link", { name: "View Japan Autumn" })).toHaveAttribute("href", "/passports/groups/trip");
    expect(within(active).getByText("700 records")).toBeVisible();
    expect(companiesApi.groups).toHaveBeenCalledWith("agency", "company", { phase: "completed", search: "", cursor: undefined, page_size: 25 }, expect.any(AbortSignal));
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reuse settings" })).not.toBeInTheDocument();
  });

  it("paginates one section without refetching the other and resets cursors after debounced search", async () => {
    vi.mocked(companiesApi.groups).mockImplementation(async (_agency, _company, params) => ({ items: params.phase === "completed" ? [{ ...group, name: params.cursor ? "Second page trip" : "First page trip" }] : [], next_cursor: params.phase === "completed" && !params.cursor ? "opaque-next" : null, has_more: params.phase === "completed" && !params.cursor }));
    mount();
    const completed = screen.getByRole("region", { name: "Completed groups" });
    await within(completed).findByText("First page trip");
    fireEvent.click(within(completed).getByRole("button", { name: "Next page" }));
    await within(completed).findByText("Second page trip");
    expect(vi.mocked(companiesApi.groups).mock.calls.filter(([, , params]) => params.phase === "active")).toHaveLength(1);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search company groups" }), { target: { value: "Japan" } });
    await waitFor(() => expect(companiesApi.groups).toHaveBeenCalledWith("agency", "company", { phase: "completed", search: "Japan", cursor: undefined, page_size: 25 }, expect.any(AbortSignal)));
  });
});
