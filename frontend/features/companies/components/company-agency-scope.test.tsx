import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { CompanyAgencyScope } from "./company-agency-scope";
import { CompanyDirectory } from "./company-directory";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
vi.mock("@/features/auth/services/session-state", () => ({ prepareSensitiveBrowserStateForUser: vi.fn() }));
const owner: User = {
  id: "owner", full_name: "Owner", email: "owner@example.test", role: "super_admin",
  agency_id: null, is_active: true, last_login_at: null, created_at: "2026-01-01", updated_at: "2026-01-01",
};
const company = { id: "client-1", name: "Example Client", status: "active", external_reference: null, revision: 1, created_at: "2026-01-01", updated_at: "2026-01-01" };

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(<QueryClientProvider client={client}><CompanyAgencyScope><CompanyDirectory /></CompanyAgencyScope></QueryClientProvider>);
  return { ...view, client };
}

beforeEach(() => {
  vi.resetAllMocks();
  useAuthStore.setState({ user: owner, isAuthenticated: true, sessionVersion: 1, isChangingAccessLevel: false });
});

describe("direct client-company workspace", () => {
  it.each([owner, { ...owner, id: "staff", role: "agency_admin" as const, agency_id: "bound-agency" }])("opens the directory without an agency picker for $role and creates a client by name", async (user) => {
    useAuthStore.setState({ user });
    vi.mocked(apiClient.get).mockImplementation(async (url) => ({ data: url.endsWith("/workspace") ? { agency_id: "resolved-agency" } : { items: [company], next_cursor: null, has_more: false } }));
    vi.mocked(apiClient.post).mockResolvedValue({ data: { ...company, name: "New Client" } });
    mount();
    await screen.findByRole("link", { name: "Example Client" });
    expect(screen.queryByLabelText(/agency workspace/i)).not.toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledWith("/api/v1/companies/workspace", { signal: expect.any(AbortSignal) });
    expect(apiClient.get).toHaveBeenCalledWith("/api/v1/companies", expect.objectContaining({ params: expect.objectContaining({ agency_id: "resolved-agency", page_size: 25 }), signal: expect.any(AbortSignal) }));
    fireEvent.click(screen.getByRole("button", { name: "Add client company" }));
    const dialog = screen.getByRole("dialog", { name: "Add client company" });
    fireEvent.change(within(dialog).getByLabelText(/Client company name/), { target: { value: "New Client" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add client company" }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith("/api/v1/companies", { name: "New Client", external_reference: null }, { params: { agency_id: "resolved-agency" } }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("shows a configuration error and explicit retry without inventing an agency when resolution is ambiguous", async () => {
    vi.mocked(apiClient.get).mockRejectedValueOnce({ code: "COMPANY_WORKSPACE_REQUIRED" }).mockResolvedValueOnce({ data: { agency_id: "configured" } }).mockResolvedValue({ data: { items: [], next_cursor: null, has_more: false } });
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("workspace configuration");
    expect(screen.queryByRole("button", { name: "Add client company" })).not.toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByRole("button", { name: "Add client company" });
    expect(screen.queryByLabelText(/agency workspace/i)).not.toBeInTheDocument();
  });

  it("cancels a stale workspace request on account change and never opens its directory", async () => {
    let staleSignal: AbortSignal | undefined;
    let resolveOld!: (value: { data: { agency_id: string } }) => void;
    vi.mocked(apiClient.get).mockImplementation((url, config) => {
      if (url.endsWith("/workspace") && useAuthStore.getState().user?.id === owner.id) {
        staleSignal = config?.signal as AbortSignal;
        return new Promise((resolve) => { resolveOld = resolve; });
      }
      return Promise.resolve({ data: url.endsWith("/workspace") ? { agency_id: "new-agency" } : { items: [{ ...company, name: "New Account Client" }], next_cursor: null, has_more: false } });
    });
    mount();
    await waitFor(() => expect(staleSignal).toBeDefined());
    act(() => useAuthStore.getState().setSession({ ...owner, id: "other-account" }));
    await screen.findByRole("link", { name: "New Account Client" });
    expect(staleSignal?.aborted).toBe(true);
    await act(async () => resolveOld({ data: { agency_id: "old-agency" } }));
    expect(vi.mocked(apiClient.get).mock.calls.some(([url, config]) => url === "/api/v1/companies" && (config?.params as { agency_id?: string } | undefined)?.agency_id === "old-agency")).toBe(false);
  });

  it("unmounts a company editor while access changes and starts with clean state for the next session", async () => {
    let resolveNext!: (value: { data: { agency_id: string } }) => void;
    vi.mocked(apiClient.get).mockImplementation(async (url) => ({ data: url.endsWith("/workspace") ? { agency_id: "same-agency" } : { items: [company], next_cursor: null, has_more: false } }));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Add client company" }));
    fireEvent.change(screen.getByLabelText(/Client company name/), { target: { value: "Previous session draft" } });
    act(() => useAuthStore.getState().beginAccessLevelChange());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    vi.mocked(apiClient.get).mockImplementation((url) => url.endsWith("/workspace") ? new Promise((resolve) => { resolveNext = resolve; }) : Promise.resolve({ data: { items: [company], next_cursor: null, has_more: false } }));
    act(() => useAuthStore.getState().setSession({ ...owner, role: "agency_admin", agency_id: "same-agency" }));
    expect(screen.queryByRole("link", { name: "Example Client" })).not.toBeInTheDocument();
    await waitFor(() => expect(resolveNext).toBeDefined());
    await act(async () => resolveNext({ data: { agency_id: "same-agency" } }));
    fireEvent.click(await screen.findByRole("button", { name: "Add client company" }));
    expect(screen.getByLabelText(/Client company name/)).toHaveValue("");
  });
});
