import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import apiClient from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { useCompany } from "../hooks/use-companies";
import { CompanySettings } from "./company-settings";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn(), put: vi.fn() } }));
const policy = { company_id: "company", enabled: false, revision: 4, notice_text: "Travellers verify their identity before reviewing saved documents." };
const user: User = { id: "owner", role: "agency_admin", agency_id: "agency", full_name: "Owner", email: "owner@example.test", is_active: true, last_login_at: null, created_at: "2026-01-01", updated_at: "2026-01-01" };
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{children}</QueryClientProvider>;
}
beforeEach(() => { vi.resetAllMocks(); useAuthStore.setState({ user, sessionVersion: 1, isChangingAccessLevel: false }); });

describe("company saved document setting", () => {
  it("saves a single toggle with the current revision and no policy or group tuning fields", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: policy });
    vi.mocked(apiClient.put).mockResolvedValue({ data: { ...policy, enabled: true, revision: 5 } });
    render(<CompanySettings agencyId="agency" companyId="company" active />, { wrapper });
    const toggle = await screen.findByRole("switch", { name: "Use saved documents" });
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByText(policy.notice_text).closest("details")).not.toHaveAttribute("open");
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).toBeChecked());
    expect(apiClient.put).toHaveBeenCalledExactlyOnceWith("/api/v1/companies/company/reuse-policy", { enabled: true, expected_revision: 4 }, { params: { agency_id: "agency" } });
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it("keeps the saved value on conflict and reloads before another attempt", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: policy }).mockResolvedValueOnce({ data: { ...policy, enabled: true, revision: 5 } });
    vi.mocked(apiClient.put).mockRejectedValue({ status: 409 });
    render(<CompanySettings agencyId="agency" companyId="company" active />, { wrapper });
    fireEvent.click(await screen.findByRole("switch", { name: "Use saved documents" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not saved");
    expect(screen.getByRole("switch")).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByRole("switch")).toBeChecked());
    expect(apiClient.put).toHaveBeenCalledTimes(1);
  });

  it("does not enable saved documents for an inactive company", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: policy });
    render(<CompanySettings agencyId="agency" companyId="company" active={false} />, { wrapper });
    expect(await screen.findByRole("switch", { name: "Use saved documents" })).toBeDisabled();
    expect(apiClient.put).not.toHaveBeenCalled();
  });

  it("sends only one save while the previous change is still pending", async () => {
    let finishSave!: (value: { data: typeof policy }) => void;
    vi.mocked(apiClient.get).mockResolvedValue({ data: policy });
    vi.mocked(apiClient.put).mockImplementation(() => new Promise((resolve) => { finishSave = resolve; }));
    render(<CompanySettings agencyId="agency" companyId="company" active />, { wrapper });
    const toggle = await screen.findByRole("switch", { name: "Use saved documents" });
    fireEvent.click(toggle);
    fireEvent.click(toggle);
    await waitFor(() => expect(apiClient.put).toHaveBeenCalledTimes(1));
    expect(toggle).toBeDisabled();
    expect(toggle).not.toBeChecked();
    await act(async () => finishSave({ data: { ...policy, enabled: true, revision: 5 } }));
    await waitFor(() => expect(toggle).toBeChecked());
    expect(toggle).not.toBeDisabled();
  });

  it("refreshes the active company revision after saving without refetching its policy", async () => {
    let revision = 2;
    vi.mocked(apiClient.get).mockImplementation(async (url) => ({ data: url.endsWith("/reuse-policy") ? policy : { id: "company", revision } }));
    vi.mocked(apiClient.put).mockImplementation(async () => { revision = 3; return { data: { ...policy, enabled: true, revision: 5 } }; });
    function CompanyContext() {
      const company = useCompany("agency", "company");
      return <><p>Company revision: {company.data?.revision}</p><CompanySettings agencyId="agency" companyId="company" active /></>;
    }
    render(<CompanyContext />, { wrapper });
    await screen.findByText("Company revision: 2");
    fireEvent.click(await screen.findByRole("switch"));
    await screen.findByText("Company revision: 3");
    expect(vi.mocked(apiClient.get).mock.calls.filter(([url]) => url.endsWith("/reuse-policy"))).toHaveLength(1);
  });

  it("hides the saved switch and sends no new request while access is changing", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: policy });
    render(<CompanySettings agencyId="agency" companyId="company" active />, { wrapper });
    await screen.findByRole("switch");
    act(() => useAuthStore.setState({ isChangingAccessLevel: true }));
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledTimes(1);
    expect(apiClient.put).not.toHaveBeenCalled();
  });
});
