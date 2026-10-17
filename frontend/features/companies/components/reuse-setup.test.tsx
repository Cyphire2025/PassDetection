import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { CompanyReusePolicy } from "./company-reuse-policy";
import { GroupReuseDialog } from "./group-reuse-dialog";
import type { CompanyGroup } from "../types";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn(), put: vi.fn() } }));
function wrapper({ children }: { children: React.ReactNode }) { return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{children}</QueryClientProvider>; }
beforeEach(() => vi.clearAllMocks());
describe("explicit reuse configuration", () => {
  it("loads policy on demand and requires administrator-supplied purpose, notice and basis", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { enabled: false, revision: 0, purpose_version: null, notice_version: null, processing_basis: null, retention_mode: "until_withdrawn" } });
    vi.mocked(apiClient.put).mockResolvedValue({ data: {} });
    render(<CompanyReusePolicy agencyId="agency" companyId="company" active />, { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Configure reuse" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: /Enable returning/ }));
    expect(screen.getByRole("button", { name: "Save reuse settings" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Documented purpose version", { exact: false }), { target: { value: "travel-v2" } });
    fireEvent.change(screen.getByLabelText("Privacy notice version", { exact: false }), { target: { value: "notice-v1" } });
    fireEvent.change(screen.getByLabelText("Documented processing basis", { exact: false }), { target: { value: "Documented traveller consent" } });
    fireEvent.click(screen.getByRole("button", { name: "Save reuse settings" }));
    await waitFor(() => expect(apiClient.put).toHaveBeenCalledWith("/api/v1/companies/company/reuse-policy", { enabled: true, expected_revision: 0, retention_mode: "until_withdrawn", purpose_version: "travel-v2", notice_version: "notice-v1", processing_basis: "Documented traveller consent" }, { params: { agency_id: "agency" } }));
  });

  it("sends config and group revisions and preserves exact identifier settings", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { group_id: "group", enabled: false, revision: 2, group_revision: 9, roster_mode: "closed", individual_identifier_type: null, identifier_required: false } });
    vi.mocked(apiClient.put).mockResolvedValue({ data: {} });
    const onClose = vi.fn();
    render(<GroupReuseDialog agencyId="agency" companyId="company" group={{ id: "group", name: "Trip", status: "active", import_only: false } as CompanyGroup} onClose={onClose} />, { wrapper });
    fireEvent.click(await screen.findByRole("checkbox", { name: /Enable verified/ }));
    fireEvent.change(screen.getByLabelText("Traveller roster"), { target: { value: "open" } });
    fireEvent.change(screen.getByLabelText("Individual code type (optional)", { exact: false }), { target: { value: "staff_code" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Require this individual/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save group reuse settings" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(apiClient.put).toHaveBeenCalledWith("/api/v1/companies/company/groups/group/reuse-config", { enabled: true, expected_revision: 2, expected_group_revision: 9, roster_mode: "open", individual_identifier_type: "staff_code", identifier_required: true }, { params: { agency_id: "agency" } });
  });
});
