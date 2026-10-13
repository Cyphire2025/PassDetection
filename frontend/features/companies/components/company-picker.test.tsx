import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { companiesApi } from "../api/companies.api";
import type { CompanyReference } from "../types";
import { CompanyPicker } from "./company-picker";

vi.mock("../api/companies.api", () => ({ companiesApi: { lookup: vi.fn() } }));
const selected: CompanyReference = { id: "old-company", name: "Previous Company", status: "inactive" };

function Picker({ initial = null }: { initial?: CompanyReference | null }) {
  const [value, setValue] = useState(initial);
  return <CompanyPicker agencyId="agency-1" value={value} onChange={setValue} />;
}
function renderPicker(initial?: CompanyReference) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><Picker initial={initial} /></QueryClientProvider>);
}

beforeEach(() => { vi.mocked(companiesApi.lookup).mockReset(); });

describe("company picker", () => {
  it("retains an inactive selection outside the results and uses bounded server cursor pages", async () => {
    vi.mocked(companiesApi.lookup)
      .mockResolvedValueOnce({ items: [{ id: "company-1", name: "Alpha", status: "active" }], next_cursor: "opaque-next", has_more: true })
      .mockResolvedValueOnce({ items: [{ id: "company-251", name: "Beyond the old company limit", status: "active" }], next_cursor: null, has_more: false });
    renderPicker(selected);
    expect(screen.getByRole("button", { name: /Previous Company \(Inactive\)/ })).toBeInTheDocument();
    expect(companiesApi.lookup).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Previous Company/ }));
    await screen.findByRole("option", { name: "Alpha" });
    fireEvent.click(screen.getByRole("button", { name: "More companies" }));
    await screen.findByRole("option", { name: "Beyond the old company limit" });
    expect(companiesApi.lookup).toHaveBeenLastCalledWith("agency-1", { search: "", cursor: "opaque-next", page_size: 20 }, expect.any(AbortSignal));
    const input = screen.getByRole("combobox", { name: "Search companies" });
    expect(input).toHaveAttribute("aria-activedescendant");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("button", { name: /Beyond the old company limit/ })).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("debounces search, cancels stale requests, and never offers stale results for selection", async () => {
    const signals: AbortSignal[] = [];
    vi.mocked(companiesApi.lookup).mockImplementation(async (_agency, params, signal) => {
      signals.push(signal!);
      if (!params.search) return new Promise(() => {});
      return { items: [{ id: "final", name: "Final search result", status: "active" }], next_cursor: null, has_more: false };
    });
    const view = renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /Select a company/ }));
    await waitFor(() => expect(companiesApi.lookup).toHaveBeenCalledTimes(1));
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "Fi" } });
    fireEvent.change(input, { target: { value: "Final" } });
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    await screen.findByRole("option", { name: "Final search result" });
    expect(companiesApi.lookup).toHaveBeenCalledTimes(2);
    expect(signals[0].aborted).toBe(true);
    view.unmount();
  });
});
