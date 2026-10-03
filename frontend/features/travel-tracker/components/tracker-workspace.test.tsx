import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { travelTrackerApi } from "../api";
import type { TrackerFilters, TrackerImportPreview, TrackerMarkRequest, TrackerPassenger } from "../types";
import { TrackerWorkspace } from "./tracker-workspace";

vi.mock("../api", () => ({ travelTrackerApi: { roster: vi.fn(), mark: vi.fn(), preview: vi.fn(), export: vi.fn() } }));
vi.mock("@/components/shared/intent-prefetch-link", () => ({ IntentPrefetchLink: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));

let passengers: TrackerPassenger[];
const passenger = (id: number): TrackerPassenger => ({
  id: `passenger-${id}`, full_name: `Passenger ${String(id).padStart(3, "0")}`, given_name: "Passenger", surname: String(id),
  passport_number: `AB${id}`, nationality: "IND", gender: "F", date_of_birth: "1990-01-01", date_of_expiry: "2030-01-01",
  email: null, phone: null, departure_city: "Delhi", submission_status: "submitted", visa_applied: false, flight_booked: false,
  visa_updated_at: null, flight_updated_at: null,
});
function getCounts(track: "visa" | "flight") {
  const marked = passengers.filter((entry) => track === "visa" ? entry.visa_applied : entry.flight_booked).length;
  return { total: passengers.length, marked, pending: passengers.length - marked };
}
function matching(filters: Pick<TrackerFilters, "track" | "status" | "search">) {
  return passengers.filter((entry) => {
    const marked = filters.track === "visa" ? entry.visa_applied : entry.flight_booked;
    return (filters.status === "all" || (filters.status === "marked" ? marked : !marked)) && entry.full_name.toLowerCase().includes(filters.search.toLowerCase());
  });
}
function renderTracker() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><TrackerWorkspace groupId="group-1" /></QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  passengers = Array.from({ length: 51 }, (_, index) => passenger(index + 1));
  vi.mocked(travelTrackerApi.roster).mockImplementation(async (_id, filters) => {
    const filtered = matching(filters);
    return {
      group: { id: "group-1", name: "Japan Tour", destination: "Japan", travel_date: "2026-12-01", return_date: null, status: "active", total: passengers.length, visa_marked: getCounts("visa").marked, flight_marked: getCounts("flight").marked },
      counts: getCounts(filters.track), passengers: filtered.slice((filters.page - 1) * filters.page_size, filters.page * filters.page_size),
      total: filtered.length, page: filters.page, page_size: filters.page_size,
    };
  });
  vi.mocked(travelTrackerApi.mark).mockImplementation(async (_id, request: TrackerMarkRequest) => {
    const ids = "passenger_ids" in request ? request.passenger_ids : matching({ ...request.selection, track: request.track }).map((entry) => entry.id);
    let updated = 0;
    passengers = passengers.map((entry) => {
      if (!ids.includes(entry.id)) return entry;
      const before = request.track === "visa" ? entry.visa_applied : entry.flight_booked;
      if (before !== request.marked) updated += 1;
      return { ...entry, [request.track === "visa" ? "visa_applied" : "flight_booked"]: request.marked };
    });
    return { updated_count: updated, unchanged_count: ids.length - updated, passenger_ids: ids, counts: getCounts(request.track) };
  });
  vi.mocked(travelTrackerApi.export).mockResolvedValue(undefined);
});

it("marks with one row action, keeps visa and flight separate, and reverses the last mark", async () => {
  const user = userEvent.setup();
  renderTracker();
  await user.click(await screen.findByRole("button", { name: "Passenger 001: Mark visa applied" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Passenger 001: Mark visa applied" })).not.toBeInTheDocument());
  expect(travelTrackerApi.mark).toHaveBeenCalledWith("group-1", { track: "visa", marked: true, passenger_ids: ["passenger-1"] });
  expect(passengers[0]).toMatchObject({ visa_applied: true, flight_booked: false });
  await user.click(screen.getByRole("button", { name: "Undo last change" }));
  await screen.findByRole("button", { name: "Passenger 001: Mark visa applied" });
  expect(passengers[0].visa_applied).toBe(false);
  screen.getByRole("tab", { name: "Visa applications" }).focus();
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: "Flight bookings" })).toHaveFocus();
  expect(screen.getByRole("tabpanel")).toHaveAccessibleName("Flight bookings");
  await user.click(await screen.findByRole("button", { name: "Passenger 001: Mark flight booked" }));
  await waitFor(() => expect(passengers[0].flight_booked).toBe(true));
  expect(passengers[0].visa_applied).toBe(false);
});

it("uses server selection across every page and clamps a emptied last page back to useful results", async () => {
  const user = userEvent.setup();
  renderTracker();
  await screen.findByRole("button", { name: "Passenger 001: Mark visa applied" });
  await user.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByRole("button", { name: "Passenger 051: Mark visa applied" });
  await user.click(screen.getByRole("button", { name: "Mark this page (1)" }));
  await screen.findByRole("button", { name: "Passenger 001: Mark visa applied" });
  expect(screen.queryByRole("button", { name: "Next page" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Mark filtered (50)" }));
  const dialog = screen.getByRole("dialog");
  expect(dialog).toHaveTextContent("across all pages");
  await user.click(within(dialog).getByRole("button", { name: "Mark filtered passengers" }));
  await waitFor(() => expect(travelTrackerApi.mark).toHaveBeenLastCalledWith("group-1", { track: "visa", marked: true, selection: { status: "pending", search: "" }, expected_count: 50 }));
  await screen.findByText("All visa passengers are marked");
  expect(passengers.every((entry) => entry.visa_applied)).toBe(true);
});

it("exports complete marked and pending rosters despite an active passenger search", async () => {
  const user = userEvent.setup();
  renderTracker();
  await screen.findByRole("button", { name: "Passenger 001: Mark visa applied" });
  await user.type(screen.getByRole("searchbox", { name: "Search tracker passengers" }), "Passenger 001");
  await waitFor(() => expect(screen.queryByRole("button", { name: "Passenger 002: Mark visa applied" })).not.toBeInTheDocument());
  await user.click(screen.getByRole("button", { name: "Marked Excel" }));
  await waitFor(() => expect(travelTrackerApi.export).toHaveBeenCalledWith("group-1", "Japan Tour", "visa", "marked"));
  await user.click(screen.getByRole("button", { name: "Pending Excel" }));
  await waitFor(() => expect(travelTrackerApi.export).toHaveBeenCalledWith("group-1", "Japan Tour", "visa", "pending"));
});

it("reviews unmatched and ambiguous import rows, then applies only the matched IDs", async () => {
  const preview: TrackerImportPreview = {
    track: "visa", marked: true, total_rows: 3, matched_count: 1, ambiguous_count: 1, unmatched_count: 1, duplicate_count: 0, passenger_ids: ["passenger-1"],
    rows: [
      { row_number: 2, name: "Passenger 001", passport_number: null, passenger_id: "passenger-1", passenger_name: "Passenger 001", status: "matched", reason: "Unique full name" },
      { row_number: 3, name: "Same Name", passport_number: null, passenger_id: null, passenger_name: null, status: "ambiguous", reason: "More than one passenger shares this name" },
      { row_number: 4, name: "Missing Name", passport_number: null, passenger_id: null, passenger_name: null, status: "unmatched", reason: "No match in this group" },
    ],
  };
  vi.mocked(travelTrackerApi.preview).mockResolvedValue(preview);
  const user = userEvent.setup();
  renderTracker();
  await screen.findByRole("button", { name: "Passenger 001: Mark visa applied" });
  await user.click(screen.getByRole("button", { name: "Update from Excel / list" }));
  const dialog = screen.getByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Paste names" }));
  await user.type(within(dialog).getByRole("textbox", { name: "Passenger names to match" }), "Passenger 001\nSame Name\nMissing Name");
  await user.click(within(dialog).getByRole("button", { name: "Preview matches" }));
  expect(await within(dialog).findByText("More than one passenger shares this name")).toBeVisible();
  expect(within(dialog).getByText("No match in this group")).toBeVisible();
  expect(travelTrackerApi.mark).not.toHaveBeenCalled();
  await user.click(within(dialog).getByRole("button", { name: "Apply 1 matches" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(travelTrackerApi.mark).toHaveBeenCalledWith("group-1", { track: "visa", marked: true, passenger_ids: ["passenger-1"] });
});

it("shows a failed mark without claiming success and restores the pending row for retry", async () => {
  vi.mocked(travelTrackerApi.mark).mockRejectedValueOnce({ message: "Connection interrupted" });
  const user = userEvent.setup();
  renderTracker();
  await user.click(await screen.findByRole("button", { name: "Passenger 001: Mark visa applied" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Connection interrupted");
  await waitFor(() => expect(screen.getByRole("button", { name: "Passenger 001: Mark visa applied" })).toBeEnabled());
  expect(passengers[0].visa_applied).toBe(false);
  expect(screen.queryByText(/passenger updated/)).not.toBeInTheDocument();
});
