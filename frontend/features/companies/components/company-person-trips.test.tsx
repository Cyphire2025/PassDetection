import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { companiesApi } from "../api/companies.api";
import { CompanyPersonTrips } from "./company-person-trips";

vi.mock("../api/companies.api", () => ({ companiesApi: { history: vi.fn() } }));
vi.mock("../hooks/use-company-session", () => ({ useCompanySession: () => ({ key: "session", ready: true }) }));
const trip = { id: "trip", group_id: "group", group_name: "Autumn tour", travel_date: "2026-10-14", lifecycle: "active", participation_status: "accepted", document_revision: 3 };
beforeEach(() => vi.resetAllMocks());

it("loads a bounded cursor history and removes saved rows after an access denial", async () => {
  vi.mocked(companiesApi.history).mockResolvedValueOnce({ items: [trip], next_cursor: "next-trip-page" }).mockResolvedValueOnce({ items: [{ ...trip, id: "old-trip", group_name: "Earlier tour" }], next_cursor: null }).mockRejectedValue({ status: 403 });
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><CompanyPersonTrips agencyId="agency" companyId="company" personId="person" /></QueryClientProvider>);
  expect(await screen.findByRole("link", { name: "Autumn tour" })).toHaveAttribute("href", "/passports/groups/group");
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByRole("link", { name: "Earlier tour" });
  expect(companiesApi.history).toHaveBeenLastCalledWith("agency", "company", "person", "next-trip-page", expect.any(AbortSignal));
  await act(async () => { await client.invalidateQueries(); });
  await waitFor(() => expect(screen.queryByRole("link", { name: "Earlier tour" })).not.toBeInTheDocument());
  expect(screen.getByRole("alert")).toHaveTextContent("Trip history could not be loaded");
});
