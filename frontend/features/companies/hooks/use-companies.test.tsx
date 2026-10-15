import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import type { User } from "@/types";
import { useAuthStore } from "@/stores/auth.store";
import { companiesApi } from "../api/companies.api";
import { companyKeys, useCompanies, useCompany, useCompanyGroups, useCompanyLookup, useCompanySummary } from "./use-companies";
import type { Company, CursorPage } from "../types";

vi.mock("../api/companies.api", () => ({ companiesApi: { list: vi.fn(), get: vi.fn(), lookup: vi.fn(), summary: vi.fn(), groups: vi.fn() } }));
const owner: User = { id: "owner", role: "super_admin", agency_id: "agency", full_name: "Owner", email: "owner@example.test", is_active: true, last_login_at: null, created_at: "2026-01-01", updated_at: "2026-01-01" };
const page = (name: string): CursorPage<Company> => ({ items: [{ id: "client", name, status: "active", revision: 1, external_reference: null, created_at: "2026-01-01", updated_at: "2026-01-01" }], next_cursor: null, has_more: false });

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { client, wrapper };
}

beforeEach(() => {
  vi.resetAllMocks();
  useAuthStore.setState({ user: owner, sessionVersion: 1, isChangingAccessLevel: false });
});

describe("company cache boundaries", () => {
  it("does not request any metadata during an access change", () => {
    useAuthStore.setState({ isChangingAccessLevel: true });
    const { wrapper } = setup();
    renderHook(() => {
      useCompanies("agency", {});
      useCompany("agency", "company");
      useCompanySummary("agency", "company");
      useCompanyGroups("agency", "company", {});
      useCompanyLookup("agency", {});
    }, { wrapper });
    for (const method of Object.values(companiesApi)) expect(method).not.toHaveBeenCalled();
  });

  it("removes a cached page immediately when access starts changing", async () => {
    vi.mocked(companiesApi.list).mockResolvedValue(page("Cached company"));
    const { wrapper } = setup();
    const result = renderHook(() => useCompanies("agency", {}), { wrapper });
    await waitFor(() => expect(result.result.current.data?.items[0].name).toBe("Cached company"));
    act(() => useAuthStore.setState({ isChangingAccessLevel: true }));
    expect(result.result.current.data).toBeUndefined();
    expect(companiesApi.list).toHaveBeenCalledTimes(1);
  });

  it("reuses a fresh page after remount/refocus and refreshes it when a company mutation invalidates the agency", async () => {
    vi.mocked(companiesApi.list).mockResolvedValue(page("Client"));
    const { client, wrapper } = setup();
    const first = renderHook(() => useCompanies("agency", { page_size: 25 }), { wrapper });
    await waitFor(() => expect(first.result.current.data?.items[0].name).toBe("Client"));
    first.unmount();
    const next = renderHook(() => useCompanies("agency", { page_size: 25 }), { wrapper });
    expect(next.result.current.data?.items[0].name).toBe("Client");
    expect(next.result.current.isLoading).toBe(false);
    await act(async () => { focusManager.setFocused(false); focusManager.setFocused(true); });
    expect(companiesApi.list).toHaveBeenCalledTimes(1);
    await act(async () => { await client.invalidateQueries({ queryKey: companyKeys.scope("agency") }); });
    expect(companiesApi.list).toHaveBeenCalledTimes(2);
    next.unmount();
    client.clear();
  });

  it("never reuses the prior account's page for another account in the same agency", async () => {
    let resolveNew!: (value: CursorPage<Company>) => void;
    vi.mocked(companiesApi.list).mockResolvedValueOnce(page("Prior account data")).mockImplementationOnce(() => new Promise((resolve) => { resolveNew = resolve; }));
    const { client, wrapper } = setup();
    const result = renderHook(() => useCompanies("agency", { page_size: 25 }), { wrapper });
    await waitFor(() => expect(result.result.current.data?.items[0].name).toBe("Prior account data"));
    act(() => useAuthStore.setState({ user: { ...owner, id: "another" }, sessionVersion: 2 }));
    expect(result.result.current.data).toBeUndefined();
    await waitFor(() => expect(resolveNew).toBeDefined());
    await act(async () => resolveNew(page("New account data")));
    await waitFor(() => expect(result.result.current.data?.items[0].name).toBe("New account data"));
    result.unmount();
    client.clear();
  });

  it("cancels an old session request and ignores its late result after an access change", async () => {
    let oldSignal: AbortSignal | undefined;
    let resolveOld!: (value: CursorPage<Company>) => void;
    vi.mocked(companiesApi.list).mockImplementationOnce((_agency, _params, signal) => {
      oldSignal = signal;
      return new Promise((resolve) => { resolveOld = resolve; });
    }).mockResolvedValueOnce(page("Current access"));
    const { client, wrapper } = setup();
    const result = renderHook(() => useCompanies("agency", { page_size: 25 }), { wrapper });
    await waitFor(() => expect(oldSignal).toBeDefined());
    act(() => useAuthStore.setState({ user: { ...owner, role: "agency_admin" }, sessionVersion: 2 }));
    await waitFor(() => expect(result.result.current.data?.items[0].name).toBe("Current access"));
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => resolveOld(page("Obsolete access")));
    expect(result.result.current.data?.items[0].name).toBe("Current access");
    result.unmount();
    client.clear();
  });
});
