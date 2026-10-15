import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import type { CompanyGroup } from "../types";
import { CompanyMatchingDialog } from "./company-matching-dialog";

vi.mock("../hooks/use-company-session", () => ({ useCompanySession: () => ({ key: "review-session", ready: true }) }));
vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
const travellerId = "11111111-1111-4111-8111-111111111111";
const match = { id: "case-one", source_kind: "passport_submission", source_row_key: "22222222-2222-4222-8222-222222222222", status: "provisional", reason_code: "exact_passport", traveller_id: travellerId, revision: 3 };
const preview = { items: [match], next_cursor: "next-page", counts: { provisional: 1, unmatched: 2 }, latest_job_status: "succeeded", processed_count: 3, expected_group_revision: 9 };
const path = "/api/v1/companies/company/groups/group/travellers/matching-preview";
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><CompanyMatchingDialog agencyId="agency" companyId="company" group={{ id: "group", name: "Group under review" } as CompanyGroup} onClose={vi.fn()} /></QueryClientProvider>);
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(apiClient.get).mockResolvedValue({ data: preview }); });
async function acknowledge() {
  fireEvent.change(screen.getByLabelText(/Evidence and decision reason/), { target: { value: "Reviewed the accepted source and confirmed the exact existing profile." } });
  fireEvent.click(screen.getByRole("checkbox", { name: /reviewed the source evidence/ }));
}
describe("bounded human-reviewed matching", () => {
  it("pages by cursor and resets the cursor when the status changes", async () => {
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Next page" }));
    await waitFor(() => expect(apiClient.get).toHaveBeenLastCalledWith(path, expect.objectContaining({ params: { agency_id: "agency", status: "all", cursor: "next-page", page_size: 25 }, signal: expect.any(AbortSignal) })));
    fireEvent.change(await screen.findByRole("combobox", { name: /^Case status/ }), { target: { value: "ambiguous" } });
    await waitFor(() => expect(apiClient.get).toHaveBeenLastCalledWith(path, expect.objectContaining({ params: { agency_id: "agency", status: "ambiguous", cursor: undefined, page_size: 25 } })));
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("requires explicit proposed-person selection and evidence, then shows pending membership rather than completed collection", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { participation_id: "membership", status: "pending" } });
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Review association" }));
    expect(screen.getByRole("radio", { name: /Use the proposed traveller/ })).not.toBeChecked();
    await acknowledge();
    expect(screen.getByRole("button", { name: "Record roster decision" })).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: /Use the proposed traveller/ }));
    expect(screen.getByRole("checkbox", { name: /reviewed the source evidence/ })).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: /reviewed the source evidence/ }));
    fireEvent.click(screen.getByRole("button", { name: "Record roster decision" }));
    await screen.findByText("Roster decision saved");
    expect(apiClient.post).toHaveBeenCalledWith("/api/v1/companies/company/groups/group/travellers/matches/case-one/resolve", { traveller_id: travellerId, expected_revision: 3, expected_group_revision: 9, evidence_reviewed: true, reason: "Reviewed the accepted source and confirmed the exact existing profile." }, { params: { agency_id: "agency" } });
    expect(screen.getByText(/Membership state:/)).toHaveTextContent("pending");
    expect(screen.getByText(/does not grant document access, record consent/)).toBeVisible();
    expect(screen.queryByText("Trip information accepted")).not.toBeInTheDocument();
  });
  it("allows an exact known UUID for an unmatched source without inventing a suggestion", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { ...preview, items: [{ ...match, traveller_id: null, status: "unmatched" }] } });
    vi.mocked(apiClient.post).mockResolvedValue({ data: { participation_id: "membership", status: "pending" } });
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Review association" }));
    expect(screen.queryByRole("radio", { name: /Use the proposed traveller/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: /exact known traveller profile ID/ }));
    fireEvent.change(screen.getByRole("textbox", { name: /Known traveller profile ID/ }), { target: { value: "A1234567" } });
    await acknowledge();
    expect(screen.getByRole("button", { name: "Record roster decision" })).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: /Known traveller profile ID/ }), { target: { value: travellerId } });
    fireEvent.click(screen.getByRole("checkbox", { name: /reviewed the source evidence/ }));
    fireEvent.click(screen.getByRole("button", { name: "Record roster decision" }));
    await screen.findByText("Roster decision saved");
    expect(vi.mocked(apiClient.post).mock.calls[0][1]).toMatchObject({ traveller_id: travellerId });
  });
  it("retains evidence and blocks replay after a stale case until refreshed", async () => {
    vi.mocked(apiClient.post).mockRejectedValue({ status: 409, message: "The case or group changed. Refresh the preview." });
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Review association" }));
    fireEvent.click(screen.getByRole("radio", { name: /Use the proposed traveller/ }));
    await acknowledge();
    fireEvent.click(screen.getByRole("button", { name: "Record roster decision" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The case or group changed");
    expect(screen.getByRole("button", { name: "Record roster decision" })).toBeDisabled();
    expect(screen.getByLabelText(/Evidence and decision reason/)).toHaveValue("Reviewed the accepted source and confirmed the exact existing profile.");
    vi.mocked(apiClient.get).mockResolvedValue({ data: { ...preview, expected_group_revision: 10, items: [{ ...match, revision: 4 }] } });
    fireEvent.click(screen.getByRole("button", { name: "Refresh matching cases" }));
    fireEvent.click(await screen.findByRole("button", { name: "Review association" }));
    expect(screen.getByRole("radio", { name: /Use the proposed traveller/ })).not.toBeChecked();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });
  it("retains the queue request key after an uncertain response and shows queued status", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("Temporary queue response failure")).mockImplementationOnce(async () => { vi.mocked(apiClient.get).mockResolvedValue({ data: { ...preview, latest_job_status: "queued" } }); return { data: { job_id: "job", status: "queued" } }; });
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Run matching preview" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Run matching preview" }));
    await screen.findByText(/Latest matching job: queued/);
    expect(vi.mocked(apiClient.post).mock.calls[0]).toEqual(vi.mocked(apiClient.post).mock.calls[1]);
    expect(screen.getByRole("button", { name: "Run matching preview" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Refresh preview" })).toBeEnabled();
  });
  it("does not expose queue or resolve actions after permission denial", async () => {
    vi.mocked(apiClient.get).mockRejectedValue({ status: 403, message: "This role cannot review company matches." });
    setup();
    expect(await screen.findByRole("alert", {}, { timeout: 3000 })).toHaveTextContent("This role cannot review");
    expect(screen.queryByRole("button", { name: "Run matching preview" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review association" })).not.toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});
