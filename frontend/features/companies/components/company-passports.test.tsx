import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { CompanyPassports } from "./company-passports";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn(), patch: vi.fn() } }));
vi.mock("../hooks/use-company-session", () => ({ useCompanySession: () => ({ key: "session", ready: true }) }));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ data: { items: [{ id: "passport", passport_hint: "********67", issuing_country: "IND", document_type: "P", status: "active", is_default: true, revision: 4, issue_date: "2020-01-01", expiry_date: "2030-01-01" }], profile_revision: 9, limit_reached: false } });
});
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><CompanyPassports agencyId="agency" companyId="company" travellerId="traveller" onClose={vi.fn()} /></QueryClientProvider>);
}
describe("explicit passport status controls", () => {
  it("requires an acknowledged status decision and binds both profile and passport revisions", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({ data: undefined });
    setup();
    fireEvent.click(await screen.findByRole("button", { name: /Change status/ }));
    fireEvent.change(screen.getByLabelText("New passport status"), { target: { value: "cancelled" } });
    expect(screen.getByRole("button", { name: "Confirm passport status" })).toBeDisabled();
    expect(screen.getByText(/older passport will not be selected automatically/)).toBeVisible();
    fireEvent.click(screen.getByRole("checkbox", { name: /verified this passport/ }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm passport status" }));
    await screen.findByRole("status");
    expect(apiClient.patch).toHaveBeenCalledWith("/api/v1/companies/company/travellers/traveller/passports/passport", { status: "cancelled", expected_profile_revision: 9, expected_passport_revision: 4 }, { params: { agency_id: "agency" } });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
  });
  it("retains the selected status and shows a concurrency error without claiming success", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue({ message: "The passport changed. Refresh this view." });
    setup();
    fireEvent.click(await screen.findByRole("button", { name: /Change status/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /verified this passport/ }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm passport status" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The passport changed");
    expect(screen.getByLabelText("New passport status")).toHaveValue("lost");
    expect(screen.queryByText(/Passport status updated/)).not.toBeInTheDocument();
  });
});
