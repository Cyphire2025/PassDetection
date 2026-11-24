import type { AnchorHTMLAttributes } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DocumentDistributionGroup } from "@/types/document-distribution.types";
import { DocumentGroupList } from "./document-group-list";

const queries = vi.hoisted(() => ({ groups: vi.fn(), search: vi.fn(), retryGroups: vi.fn(), retrySearch: vi.fn() }));
vi.mock("../hooks/use-document-distribution", () => ({
  useDocumentGroups: queries.groups,
  useDocumentGroupSearch: queries.search,
}));
vi.mock("@/hooks/use-debounce", () => ({ useDebounce: (value: string) => value }));
vi.mock("@/components/shared/intent-prefetch-link", () => ({
  IntentPrefetchLink: (props: AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props} />,
}));

const group: DocumentDistributionGroup = {
  group_id: "group-1", group_name: "Bali delegates", group_status: "active",
  destination: "Bali", travel_date: null, total_passengers: 3,
  visa_assigned_count: 0, flight_ticket_assigned_count: 0,
  flight_ticket_arrival_assigned_count: 0, flight_ticket_domestic_assigned_count: 0,
  flight_ticket_domestic_arrival_assigned_count: 0, other_assigned_count: 0,
};

describe("document distribution group search", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queries.groups.mockReturnValue({ data: [], isLoading: false, error: null, refetch: queries.retryGroups });
    queries.search.mockReturnValue({ data: [group], isLoading: false, isFetching: false, error: null, refetch: queries.retrySearch });
  });

  it("renders successful server search results when the base list is empty", () => {
    queries.groups.mockReturnValue({ data: [], isLoading: false, error: new Error("Base list unavailable"), refetch: queries.retryGroups });
    render(<DocumentGroupList category="visa" />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("No groups are ready for distribution")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search document distribution groups" }), { target: { value: "delegate" } });
    expect(screen.getByRole("heading", { name: group.group_name })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Visa Documents" })).toHaveAttribute("href", "/documents/distribution/visa/group-1");
    expect(screen.queryByText("No groups are ready for distribution")).not.toBeInTheDocument();
  });

  it("keeps successful empty portfolios distinct from unavailable totals and permits explicit retry", () => {
    queries.groups.mockReturnValue({ data: undefined, isLoading: false, error: new Error("Unavailable"), refetch: queries.retryGroups });
    const view = render(<DocumentGroupList category="visa" />);
    expect(screen.queryByText("No groups are ready for distribution")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Document distribution portfolio" })).not.toBeInTheDocument();
    expect(screen.getByText("Groups unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry distribution groups" }));
    expect(queries.retryGroups).toHaveBeenCalledOnce();
    queries.groups.mockReturnValue({ data: [], isLoading: false, error: null, refetch: queries.retryGroups });
    view.rerender(<DocumentGroupList category="visa" />);
    expect(screen.getByText("No groups are ready for distribution")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Document distribution portfolio" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("distinguishes failed searches from successful no-match results and retries the search observer", () => {
    queries.search.mockReturnValue({ data: undefined, isLoading: false, isFetching: false, error: new Error("Search unavailable"), refetch: queries.retrySearch });
    const view = render(<DocumentGroupList category="visa" />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "synthetic query" } });
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("No distribution groups match this search")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry group search" }));
    expect(queries.retrySearch).toHaveBeenCalledOnce();
    expect(queries.retryGroups).not.toHaveBeenCalled();
    queries.search.mockReturnValue({ data: [], isLoading: false, isFetching: false, error: null, refetch: queries.retrySearch });
    view.rerender(<DocumentGroupList category="visa" />);
    expect(screen.getByText("No distribution groups match this search")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("retains previously successful scoped groups while a refresh is unavailable", () => {
    queries.groups.mockReturnValue({ data: [group], isLoading: false, error: new Error("Refresh unavailable"), refetch: queries.retryGroups });
    render(<DocumentGroupList category="visa" />);
    expect(screen.getByRole("heading", { name: group.group_name })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Document distribution portfolio" })).toBeInTheDocument();
    expect(screen.queryByText("Groups unavailable")).not.toBeInTheDocument();
  });

  it("allows a successful empty search when the separate portfolio query failed", () => {
    queries.groups.mockReturnValue({ data: undefined, isLoading: false, error: new Error("Portfolio unavailable"), refetch: queries.retryGroups });
    queries.search.mockReturnValue({ data: [], isLoading: false, isFetching: false, error: null, refetch: queries.retrySearch });
    render(<DocumentGroupList category="visa" />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "missing" } });
    expect(screen.getByText("No distribution groups match this search")).toBeInTheDocument();
  });

  it("shows the search empty state when an empty base list has no matches", () => {
    queries.search.mockReturnValue({ data: [], isLoading: false, isFetching: false, error: null });
    render(<DocumentGroupList category="visa" />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search document distribution groups" }), { target: { value: "missing" } });
    expect(screen.getByText("No distribution groups match this search")).toBeInTheDocument();
  });
});
