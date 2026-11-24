import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PassportGroupSummary } from "@/types/passport.types";
import { PassportList } from "./passport-list";

const fixture = vi.hoisted(() => ({
  query: { data: undefined as PassportGroupSummary[] | undefined, isLoading: false, isFetching: false, error: undefined as Error | undefined, refetch: vi.fn() },
  export: { isPending: false, isError: false, error: null, reset: vi.fn(), mutateAsync: vi.fn() },
}));
vi.mock("../hooks/use-passports", () => ({ usePassportGroups: () => fixture.query, useExportSelectedGroups: () => fixture.export }));
vi.mock("next/dynamic", () => ({ default: () => () => null }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ prefetch: vi.fn() }) }));
const group = {
  group_id: "group", group_name: "Synthetic group", group_status: "active",
  total_passports: 12, pending_review_count: 2, confirmed_count: 10, failed_count: 0,
  latest_submission_at: "2026-10-31T00:00:00Z", destination: "Dubai",
} as PassportGroupSummary;
beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(fixture.query, { data: undefined, isLoading: false, isFetching: false, error: undefined });
});

describe("passport group list query states", () => {
  it("keeps an initial failure distinct from an empty portfolio and provides explicit retry", () => {
    fixture.query.error = new Error("Synthetic unavailable");
    render(<PassportList />);
    expect(screen.getByRole("alert")).toHaveTextContent("could not be loaded");
    expect(screen.queryByRole("heading", { name: "Start the first passport group" })).not.toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "All Groups readiness summary" });
    expect(within(summary).queryByText("0")).not.toBeInTheDocument();
    expect(within(summary).getAllByText("Unavailable")).toHaveLength(4);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(fixture.query.refetch).toHaveBeenCalledOnce();
  });

  it("continues to present a successful zero portfolio as an empty state", () => {
    fixture.query.data = [];
    render(<PassportList />);
    expect(screen.getByRole("heading", { name: "Start the first passport group" })).toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "All Groups readiness summary" });
    expect(within(summary).getAllByText("0")).toHaveLength(4);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("retains saved data and selection after a refresh failure while labeling it as previously loaded", () => {
    fixture.query.data = [group];
    const { rerender } = render(<PassportList />);
    fireEvent.click(screen.getAllByRole("checkbox", { name: "Select Synthetic group" })[0]);
    fixture.query.error = new Error("Synthetic refresh failure");
    rerender(<PassportList />);
    expect(screen.getByRole("alert")).toHaveTextContent("Previously loaded groups remain visible");
    expect(screen.getByText("1 group selected for export")).toBeInTheDocument();
    for (const checkbox of screen.getAllByRole("checkbox", { name: "Select Synthetic group" })) expect(checkbox).toBeChecked();
    expect(screen.getByRole("link", { name: "Manage Group Links" })).toHaveAttribute("href", "/upload-links");
  });

  it("retains selection through destination filtering and resets only the filters", () => {
    fixture.query.data = [group, { ...group, group_id: "other", group_name: "Other group", destination: "Bali", pending_review_count: 0 }];
    render(<PassportList />);
    fireEvent.click(screen.getAllByRole("checkbox", { name: "Select Synthetic group" })[0]);
    fireEvent.change(screen.getByRole("searchbox", { name: "Filter groups by destination" }), { target: { value: "Bali" } });
    expect(screen.queryByRole("checkbox", { name: "Select Synthetic group" })).not.toBeInTheDocument();
    expect(screen.getByText("1 group selected for export")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter by review readiness"), { target: { value: "needs_review" } });
    expect(screen.getByRole("heading", { name: "No groups match this working view" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    for (const checkbox of screen.getAllByRole("checkbox", { name: "Select Synthetic group" })) expect(checkbox).toBeChecked();
    expect(screen.getByRole("searchbox", { name: "Filter groups by destination" })).toHaveValue("");
  });

  it("disables explicit retry while a replacement fetch is active", () => {
    fixture.query.error = new Error("Synthetic unavailable");
    fixture.query.isFetching = true;
    render(<PassportList />);
    const retry = screen.getByRole("button", { name: "Retry" });
    expect(retry).toBeDisabled();
    fireEvent.click(retry);
    expect(fixture.query.refetch).not.toHaveBeenCalled();
  });
});
