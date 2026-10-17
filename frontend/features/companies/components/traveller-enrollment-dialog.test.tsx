import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import type { CompanyGroup } from "../types";
import { TravellerEnrollmentDialog } from "./traveller-enrollment-dialog";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
const group = { id: "group", name: "Accepted history" } as CompanyGroup;
function setup(enabled = true, candidate = false) {
  vi.mocked(apiClient.get).mockImplementation(async (url) => ({ data: url.endsWith("reuse-policy") ? { enabled } : { items: [{ id: "source", display_name: "Reviewed Person", status: "staff_approved", extraction_revision: 7, ...(candidate ? { candidate_traveller_id: "verified-person", candidate_profile_revision: 2, candidate_change_kind: "renewal" } : {}) }], next_cursor: null, expected_group_revision: 9 } }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><TravellerEnrollmentDialog agencyId="agency" companyId="company" group={group} onClose={vi.fn()} /></QueryClientProvider>);
}
beforeEach(() => vi.clearAllMocks());
describe("explicit accepted-source enrollment", () => {
  it("requires staff to accept the verified-person association before promoting a renewal", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { traveller_id: "verified-person", copies_pending: 2 } });
    setup(true, true);
    fireEvent.click(await screen.findByRole("radio", { name: /Reviewed Person/ }));
    fireEvent.click(screen.getByRole("link", { name: "Review this saved submission" }));
    fireEvent.change(screen.getByLabelText("Reviewed issuing country"), { target: { value: "IND" } });
    fireEvent.change(screen.getByLabelText("Reviewed document type", { exact: false }), { target: { value: "P" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /inspected the source passport/ }));
    fireEvent.change(screen.getByLabelText("Recorded permission evidence reference", { exact: false }), { target: { value: "recorded-traveller-permission" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /checked the accepted document/ }));
    expect(screen.getByRole("button", { name: "Enroll accepted traveller" })).toBeDisabled();
    expect(apiClient.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Accept this renewal update/ }));
    fireEvent.click(screen.getByRole("button", { name: "Enroll accepted traveller" }));
    await screen.findByText(/2 protected document copies/);
    expect(vi.mocked(apiClient.post).mock.calls[0][1]).toMatchObject({ candidate_association_confirmed: true, source_submission_id: "source", change_kind: "renewal", reviewed_context_confirmed: true });
    expect(vi.mocked(apiClient.post).mock.calls[0][1]).not.toHaveProperty("traveller_id");
  });

  it("does not load sources when company reuse is disabled", async () => {
    setup(false);
    await screen.findByText(/Configure and enable/);
    expect(apiClient.get).toHaveBeenCalledTimes(1);
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("requires saved source and evidence, binds both revisions and reuses request identity on retry", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("Temporary failure")).mockResolvedValueOnce({ data: { traveller_id: "person", copies_pending: 2 } });
    setup();
    fireEvent.click(await screen.findByRole("radio", { name: /Reviewed Person/ }));
    expect(screen.getByRole("button", { name: "Enroll accepted traveller" })).toBeDisabled();
    fireEvent.click(screen.getByRole("link", { name: "Review this saved submission" }));
    fireEvent.change(screen.getByLabelText("Reviewed issuing country"), { target: { value: "IND" } });
    fireEvent.change(screen.getByLabelText("Reviewed document type", { exact: false }), { target: { value: "P" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /inspected the source passport/ }));
    fireEvent.change(screen.getByLabelText("Recorded permission evidence reference", { exact: false }), { target: { value: "signed-consent-record-442" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /checked the accepted document/ }));
    fireEvent.click(screen.getByRole("button", { name: "Enroll accepted traveller" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Enroll accepted traveller" }));
    await screen.findByText(/2 protected document copies/);
    const calls = vi.mocked(apiClient.post).mock.calls;
    expect(calls[0]).toEqual(calls[1]);
    expect(calls[0][1]).toMatchObject({ source_submission_id: "source", expected_extraction_revision: 7, expected_group_revision: 9, change_kind: "initial", permission_evidence_reference: "signed-consent-record-442" });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/api/v1/companies/company/groups/group/travellers/enrollment-sources", expect.objectContaining({ params: { agency_id: "agency", search: "", cursor: undefined, page_size: 25 }, signal: expect.any(AbortSignal) })));
  });
});
