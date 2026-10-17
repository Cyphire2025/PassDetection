import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { GroupCompanyAssignment } from "./group-company-assignment";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn(), patch: vi.fn(), post: vi.fn() } }));
vi.mock("./company-picker", () => ({ CompanyPicker: ({ onChange, value }: { onChange: (value: unknown) => void; value: { name: string } | null }) => <><p>{value?.name ?? "Unassigned"}</p><button type="button" onClick={() => onChange({ id: "target", name: "Target Company", status: "active" })}>Select target company</button></> }));

const base = { id: "group-1", agency_id: "agency-1", name: "Historical Group", status: "archived", company_id: null, company: null, company_revision: 0 } as UploadLinkResponse;
const target = { id: "target", name: "Target Company", status: "active" as const };
function setup(group = base) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  useAuthStore.setState({ user: { role: "agency_admin", is_active: true, agency_id: "agency-1" } as User });
  return render(<QueryClientProvider client={client}><GroupCompanyAssignment group={group} /></QueryClientProvider>);
}
beforeEach(() => vi.clearAllMocks());

describe("company assignment", () => {
  it("saves legacy archived assignment through only the company endpoint with revision zero", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({ data: { ...base, company_id: target.id, company: target, company_revision: 1 } });
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Select target company" }));
    fireEvent.click(screen.getByRole("button", { name: "Save company assignment" }));
    await screen.findByText("Company assignment saved.");
    expect(apiClient.patch).toHaveBeenCalledExactlyOnceWith("/api/v1/upload-links/group-1/company", { company_id: "target", expected_revision: 0 }, { params: { agency_id: "agency-1" } });
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Save company assignment" })).toBeDisabled();
  });

  it("requires an impact preview, reason and both expected revisions before reassignment", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { group_id: base.id, source_company_id: "previous", target_company_id: "target", expected_revision: 4, expected_roster_revision: 17, submission_records: 700, accepted_participations: 400, active_claims: 2, active_grants: 3, manager_conflict: false, can_reassign: true } });
    vi.mocked(apiClient.post).mockResolvedValue({ data: { ...base, company_id: target.id, company: target, company_revision: 5 } });
    setup({ ...base, company_id: "previous", company: { id: "previous", name: "Previous", status: "active" }, company_revision: 4 });
    fireEvent.click(screen.getByRole("button", { name: "Select target company" }));
    fireEvent.click(screen.getByRole("button", { name: "Save company assignment" }));
    const dialog = await screen.findByRole("dialog", { name: "Review company reassignment" });
    await within(dialog).findByText("700");
    expect(within(dialog).getByRole("button", { name: "Confirm reassignment" })).toBeDisabled();
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Reason for reassignment" }), { target: { value: "Correcting client ownership" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm reassignment" }));
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith("/api/v1/companies/target/reassignments/group-1", { expected_revision: 4, expected_roster_revision: 17, reason: "Correcting client ownership" }, { params: { agency_id: "agency-1" } });
    expect(apiClient.patch).not.toHaveBeenCalled();
  });

  it("keeps manager-conflicted reassignment blocked", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { expected_revision: 4, expected_roster_revision: 17, submission_records: 700, accepted_participations: 400, active_claims: 0, active_grants: 0, manager_conflict: true, can_reassign: false } });
    setup({ ...base, company_id: "previous", company: { id: "previous", name: "Previous", status: "active" }, company_revision: 4 });
    fireEvent.click(screen.getByRole("button", { name: "Select target company" }));
    fireEvent.click(screen.getByRole("button", { name: "Save company assignment" }));
    await screen.findByText(/client-manager assignment conflicts/);
    fireEvent.change(screen.getByRole("textbox", { name: "Reason for reassignment" }), { target: { value: "Correcting client ownership" } });
    expect(screen.getByRole("button", { name: "Confirm reassignment" })).toBeDisabled();
    expect(apiClient.patch).not.toHaveBeenCalled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});
