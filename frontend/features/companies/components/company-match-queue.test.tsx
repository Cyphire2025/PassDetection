import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { companiesApi } from "../api/companies.api";
import { companyPeopleApi } from "../api/company-people.api";
import { companyMatchingApi } from "../api/company-matching.api";
import { CompanyAllData } from "./company-all-data";

vi.mock("../hooks/use-company-session", () => ({ useCompanySession: () => ({ key: "review-session", ready: true }) }));
vi.mock("../api/companies.api", () => ({ companiesApi: { groups: vi.fn() } }));
vi.mock("../api/company-people.api", () => ({ companyPeopleApi: { list: vi.fn() } }));
vi.mock("../api/company-matching.api", async (load) => ({ ...await load<object>(), companyMatchingApi: { preview: vi.fn(), enqueue: vi.fn() } }));
vi.mock("./company-data-exports", () => ({ CompanyDataExports: () => null }));
const group = { id: "group", name: "Autumn trip", status: "active" as const, submission_count: 3, import_only: false, destination: null, travel_date: null, return_date: null };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(companyPeopleApi.list).mockResolvedValue({ items: [], next_cursor: null, has_more: false });
  vi.mocked(companiesApi.groups).mockResolvedValue({ items: [group], next_cursor: "next-groups", has_more: true });
  vi.mocked(companyMatchingApi.preview).mockResolvedValue({ items: [], next_cursor: null, counts: {}, latest_job_status: null, processed_count: 0, expected_group_revision: 1 });
});
function mount() {
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><CompanyAllData agencyId="agency" companyId="company" /></QueryClientProvider>);
  return client;
}

it("opens a lazy, 25-group cursor picker from All data before requesting the selected matching queue", async () => {
  mount();
  await screen.findByText("No people yet.");
  expect(companiesApi.groups).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Review matches" }));
  await screen.findByRole("button", { name: "Review matches for Autumn trip" });
  expect(companiesApi.groups).toHaveBeenCalledExactlyOnceWith("agency", "company", { search: "", cursor: undefined, page_size: 25, phase: "all" }, expect.any(AbortSignal));
  expect(companyMatchingApi.preview).not.toHaveBeenCalled();
  vi.mocked(companiesApi.groups).mockResolvedValue({ items: [{ ...group, id: "second", name: "Second trip" }], next_cursor: null, has_more: false });
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  fireEvent.click(await screen.findByRole("button", { name: "Review matches for Second trip" }));
  await screen.findByRole("heading", { name: "Review traveller matches" });
  expect(companyMatchingApi.preview).toHaveBeenCalledExactlyOnceWith("agency", "company", "second", "all", undefined, expect.any(AbortSignal));
  expect(companyMatchingApi.enqueue).not.toHaveBeenCalled();
});

it("hides cached selectable groups and paging when refreshed access is denied", async () => {
  const client = mount();
  fireEvent.click(screen.getByRole("button", { name: "Review matches" }));
  await screen.findByRole("button", { name: "Review matches for Autumn trip" });
  vi.mocked(companiesApi.groups).mockRejectedValue({ status: 403 });
  await act(async () => { await client.invalidateQueries(); });
  await waitFor(() => expect(screen.queryByRole("button", { name: "Review matches for Autumn trip" })).not.toBeInTheDocument());
  expect(screen.queryByRole("button", { name: "Next page" })).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Groups could not be loaded");
});
