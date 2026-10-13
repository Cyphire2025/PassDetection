import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { CompanyCollectedRecords } from "./company-collected-records";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn() } }));
const record = { id: "record-1", group_id: "group-1", group_name: "Autumn Tour", display_name: "Asha Example", travel_date: "2026-10-14", status: "confirmed", created_at: "2026-10-01T00:00:00Z" };
const first = { items: [record], next_cursor: "opaque-next", has_more: true };
const last = { items: [{ ...record, id: "record-2", display_name: "Last Record" }], next_cursor: null, has_more: false };

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><CompanyCollectedRecords agencyId="agency-1" companyId="client-1" /></QueryClientProvider>);
}

beforeEach(() => vi.resetAllMocks());

describe("combined collected records", () => {
  it("loads bounded pages across assigned groups and links to their existing record screens", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: first }).mockResolvedValueOnce({ data: last });
    mount();
    expect(await screen.findByRole("link", { name: "Asha Example" })).toHaveAttribute("href", "/passports/record-1");
    expect(screen.getByRole("link", { name: "Autumn Tour" })).toHaveAttribute("href", "/passports/groups/group-1");
    expect(screen.getByText(/this is not a count of unique people/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByRole("link", { name: "Last Record" });
    expect(apiClient.get).toHaveBeenLastCalledWith("/api/v1/companies/client-1/submissions", { params: { agency_id: "agency-1", search: "", cursor: "opaque-next", page_size: 25 }, signal: expect.any(AbortSignal) });
    expect(screen.queryByRole("link", { name: "Asha Example" })).not.toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  it("does not submit short searches, cancels stale requests, and clears the cursor for a new name", async () => {
    const signals: AbortSignal[] = [];
    vi.mocked(apiClient.get).mockImplementation(async (_url, config) => {
      signals.push(config?.signal as AbortSignal);
      if (!(config?.params as { search?: string } | undefined)?.search) return new Promise(() => {});
      return { data: last };
    });
    const view = mount();
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search collected records" }), { target: { value: "As" } });
    expect(screen.getByText(/Enter at least 3 characters/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    await waitFor(() => expect(signals[0].aborted).toBe(true));
    expect(apiClient.get).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search collected records" }), { target: { value: "Asha" } });
    await screen.findByRole("link", { name: "Last Record" });
    expect(apiClient.get).toHaveBeenLastCalledWith("/api/v1/companies/client-1/submissions", { params: { agency_id: "agency-1", search: "Asha", cursor: undefined, page_size: 25 }, signal: expect.any(AbortSignal) });
    view.unmount();
  });

  it("hides previous results after a stale-cursor failure and permits restarting from the first page", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: first }).mockRejectedValueOnce({ code: "INVALID_CURSOR" }).mockResolvedValueOnce({ data: first });
    mount();
    await screen.findByRole("link", { name: "Asha Example" });
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("return to the first page");
    expect(screen.queryByRole("link", { name: "Asha Example" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "First page" }));
    await screen.findByRole("link", { name: "Asha Example" });
  });
});
