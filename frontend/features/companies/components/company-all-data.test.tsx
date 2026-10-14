import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { companyPeopleApi } from "../api/company-people.api";
import { CompanyAllData } from "./company-all-data";

vi.mock("../hooks/use-company-session", () => ({ useCompanySession: () => ({ key: "session", ready: true }) }));
vi.mock("../hooks/use-company-view-state", () => import("../test-support/navigation"));
vi.mock("../api/company-people.api", () => ({ companyPeopleApi: { list: vi.fn() } }));
vi.mock("./company-data-exports", () => ({ CompanyDataExports: () => <div>Exports</div> }));
const person = { id: "person", display_name: "Jane Sample", status: "active", revision: 1, trip_count: 2,
  submission_count: 3, document_version_count: 4, duplicate_status: "possible" as const, current_passport_last4: "1234" };
beforeEach(() => {
  vi.resetAllMocks(); window.history.replaceState(null, "", "/companies/company?tab=data");
  vi.mocked(companyPeopleApi.list).mockResolvedValue({ items: [person], has_more: false, next_cursor: null });
});

function mount() {
  return render(<QueryClientProvider client={new QueryClient()}><CompanyAllData agencyId="agency" companyId="company" /></QueryClientProvider>);
}

it("opens a full person route, shows submission counts and omits the ambiguous duplicate badge", async () => {
  mount();
  const open = await screen.findByRole("link", { name: "Open Jane Sample" });
  expect(open).toHaveAttribute("href", "/companies/company/people/person?tab=data");
  expect(screen.getByText(/3 submissions · 2 trips/)).toBeVisible();
  expect(screen.queryByText("Possible duplicate")).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByText("Up to 100 people per page")).toBeVisible();
});

it("debounces partial search, binds server sort/count filters and preserves them in the person link", async () => {
  mount(); await screen.findByRole("link", { name: "Open Jane Sample" });
  const search = screen.getByRole("searchbox", { name: "Search company people" });
  fireEvent.change(search, { target: { value: "Ja" } });
  fireEvent.change(search, { target: { value: "Jane" } });
  expect(companyPeopleApi.list).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(companyPeopleApi.list).toHaveBeenCalledTimes(2));
  fireEvent.change(screen.getByLabelText("Sort people"), { target: { value: "name_desc" } });
  fireEvent.change(screen.getByLabelText("Number of submissions"), { target: { value: "multiple" } });
  await waitFor(() => expect(companyPeopleApi.list).toHaveBeenLastCalledWith("agency", "company", {
    search: "Jane", cursor: undefined, sort: "name_desc", submissions: "multiple",
  }, expect.any(AbortSignal)));
  const url = new URL((await screen.findByRole("link", { name: "Open Jane Sample" })).getAttribute("href")!, "https://local.test");
  expect(url.searchParams.get("peopleSearch")).toBe("Jane");
  expect(url.searchParams.get("peopleSort")).toBe("name_desc");
  expect(url.searchParams.get("submissions")).toBe("multiple");
});

it("explains a stopped index without hiding records or promising continued progress", async () => {
  vi.mocked(companyPeopleApi.list).mockResolvedValue({ items: [person], has_more: false, next_cursor: null,
    indexing_pending: true, indexing_failed: true });
  mount();
  expect(await screen.findByRole("link", { name: "Open Jane Sample" })).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("Some records could not be added to this list");
  expect(screen.queryByText(/Saved records are being indexed/)).not.toBeInTheDocument();
});

it("restarts an expired directory generation while preserving search and filters", async () => {
  window.history.replaceState(null, "", "/companies/company?tab=data&peopleSearch=Jane&peopleSort=name_desc&submissions=multiple&peopleCursor=old-generation");
  vi.mocked(companyPeopleApi.list).mockRejectedValueOnce({ status: 409, code: "DIRECTORY_CHANGED" })
    .mockResolvedValue({ items: [person], has_more: false, next_cursor: null });
  mount();
  await screen.findByRole("link", { name: "Open Jane Sample" });
  expect(companyPeopleApi.list).toHaveBeenCalledTimes(2);
  expect(companyPeopleApi.list).toHaveBeenLastCalledWith("agency", "company", {
    search: "Jane", cursor: undefined, sort: "name_desc", submissions: "multiple",
  }, expect.any(AbortSignal));
  expect(new URLSearchParams(window.location.search).has("peopleCursor")).toBe(false);
});

it("does not retry an access denial or discard its cursor automatically", async () => {
  window.history.replaceState(null, "", "/companies/company?tab=data&peopleCursor=existing-page");
  vi.mocked(companyPeopleApi.list).mockRejectedValue({ status: 403, code: "FORBIDDEN" });
  mount();
  await screen.findByText("People could not be loaded.");
  expect(companyPeopleApi.list).toHaveBeenCalledTimes(1);
  expect(new URLSearchParams(window.location.search).get("peopleCursor")).toBe("existing-page");
});

it("keeps a one-character prefix local until it can be searched efficiently", async () => {
  mount(); await screen.findByRole("link", { name: "Open Jane Sample" });
  fireEvent.change(screen.getByRole("searchbox", { name: "Search company people" }), { target: { value: "J" } });
  expect(await screen.findByText("Enter at least 2 characters per name part.")).toBeVisible();
  await new Promise((resolve) => setTimeout(resolve, 300));
  expect(companyPeopleApi.list).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Refresh people" })).toBeDisabled();
  fireEvent.change(screen.getByRole("searchbox", { name: "Search company people" }), { target: { value: "Ja" } });
  await waitFor(() => expect(companyPeopleApi.list).toHaveBeenCalledTimes(2));
});
