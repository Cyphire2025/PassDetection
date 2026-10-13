import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { companiesApi } from "../api/companies.api";
import { companyKeys } from "../hooks/use-companies";
import type { CompanyReference } from "../types";
import { CompanyPicker } from "./company-picker";

vi.mock("../api/companies.api", () => ({ companiesApi: { lookup: vi.fn() } }));
const selected: CompanyReference = { id: "old-company", name: "Previous Company", status: "inactive" };
const user: User = { id: "owner", role: "agency_admin", agency_id: "agency-1", full_name: "Owner", email: "owner@example.test", is_active: true, last_login_at: null, created_at: "2026-01-01", updated_at: "2026-01-01" };

function Picker({ initial = null }: { initial?: CompanyReference | null }) {
  const [value, setValue] = useState(initial);
  return <CompanyPicker agencyId="agency-1" value={value} onChange={setValue} />;
}
function renderPicker(initial?: CompanyReference) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { ...render(<QueryClientProvider client={client}><Picker initial={initial} /></QueryClientProvider>), client };
}

beforeEach(() => { vi.mocked(companiesApi.lookup).mockReset(); useAuthStore.setState({ user, sessionVersion: 1, isChangingAccessLevel: false }); });

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

  it("removes cached choices and pagination after a denied background refresh", async () => {
    vi.mocked(companiesApi.lookup)
      .mockResolvedValueOnce({ items: [{ id: "old-visible", name: "Previously Visible", status: "active" }], next_cursor: "next", has_more: true })
      .mockRejectedValueOnce({ status: 403 });
    const { client } = renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /Select a company/ }));
    await screen.findByRole("option", { name: "Previously Visible" });
    await act(async () => client.invalidateQueries({ queryKey: companyKeys.scope("agency-1") }));
    await screen.findByText("Company search could not be loaded.");
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "More companies" })).not.toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });
    expect(screen.getByRole("button", { name: /Select a company/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry company search" })).toBeEnabled();
  });
});
