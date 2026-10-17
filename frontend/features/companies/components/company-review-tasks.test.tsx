import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { CompanyReviewTasks } from "./company-review-tasks";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn(), patch: vi.fn() } }));
const task = { id: "task", group_id: "group", traveller_id: "traveller", source_submission_id: "source", old_document_revision_id: "old", new_document_revision_id: "new", status: "pending", reason_code: "DOCUMENT_CHANGED", revision: 2, expected_participation_revision: 3, current_participation_revision: 5, created_at: "2026-10-13T12:00:00Z", resolved_at: null, resolution_reason: null };
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><CompanyReviewTasks agencyId="agency" companyId="company" /></QueryClientProvider>);
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(apiClient.get).mockResolvedValue({ data: { items: [task], next_cursor: "cursor-2", has_more: true } }); });
describe("operational document review tasks", () => {
  it("loads one tenant-scoped page and records an explicit review with current concurrency revisions", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({ data: { ...task, status: "resolved", revision: 3 } });
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Record review outcome" }));
    expect(screen.getByRole("button", { name: "Save review outcome" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Review note/), { target: { value: "Checked ticket and visa with current document." } });
    fireEvent.click(screen.getByRole("checkbox", { name: /reviewed the affected trip/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save review outcome" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(apiClient.patch).toHaveBeenCalledWith("/api/v1/companies/company/review-tasks/task", { expected_revision: 2, expected_participation_revision: 5, resolution: "resolved", reason: "Checked ticket and visa with current document." }, { params: { agency_id: "agency" } });
    expect(apiClient.get).toHaveBeenCalledWith("/api/v1/companies/company/review-tasks", expect.objectContaining({ params: { agency_id: "agency", status: "pending", cursor: undefined, page_size: 25 }, signal: expect.any(AbortSignal) }));
  });
  it("keeps review notes after a conflict and does not mark the task complete", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue({ status: 409, message: "The trip changed; refresh and review again." });
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Record review outcome" }));
    fireEvent.change(screen.getByLabelText(/Review note/), { target: { value: "Reviewed ticket document details." } });
    fireEvent.click(screen.getByRole("checkbox", { name: /reviewed the affected trip/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save review outcome" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The trip changed");
    expect(screen.getByLabelText(/Review note/)).toHaveValue("Reviewed ticket document details.");
    expect(screen.getByRole("dialog")).toBeVisible();
  });
});
