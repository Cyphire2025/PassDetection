import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { DocumentRecipientPanel } from "./document-recipient-panel";

const f = vi.hoisted(() => ({ review: vi.fn(), manual: vi.fn(), unassign: vi.fn(), preview: vi.fn() }));
vi.mock("../hooks/use-document-distribution", () => ({
  useDocumentReview: () => ({ data: f.review(), refetch: vi.fn(), isLoading: false }),
  useManualPassengerDocumentUpload: () => ({ mutate: f.manual, reset: vi.fn(), isPending: false }),
  useUnassignDistributionDocuments: () => ({ mutate: f.unassign, reset: vi.fn(), isPending: false }),
}));
vi.mock("../api/document-updates.api", () => ({ documentUpdatesApi: { preview: f.preview } }));
vi.mock("./document-broadcast-actions", () => ({ DocumentBroadcastActions: (props: { broadcastGroupId: string; onSendDocuments: () => void }) => <button type="button" onClick={props.onSendDocuments}>Send options for {props.broadcastGroupId}</button> }));
vi.mock("./document-recipient-send-dialog", () => ({ DocumentRecipientSendDialog: (props: { initialDocumentIds?: string[]; broadcastGroupId: string }) => <output aria-label="Chosen documents">{JSON.stringify({ ids: props.initialDocumentIds, scope: props.broadcastGroupId })}</output> }));

const document = { id: "doc", original_filename: "flight.pdf", match_status: "matched", match_confidence: 1, delivery_status: "delivery_unknown", updated_at: "2026-10-16T00:00:00Z" };
beforeEach(() => {
  vi.clearAllMocks();
  f.review.mockReturnValue({ status: "saved", review_rows: [
    { passenger_id: "inside", passenger_name: "Inside broadcast", documents: [document], assigned_pdf_count: 1, shared_pdf_count: 1 },
    { passenger_id: "missing", passenger_name: "Missing document", documents: [], assigned_pdf_count: 0 },
    { passenger_id: "outside", passenger_name: "Other broadcast", documents: [{ ...document, id: "outside-document" }] },
  ] });
  f.preview.mockResolvedValue({ recipients: [{ passenger_id: "inside", eligible: false }, { passenger_id: "missing", eligible: true }] });
});

function show(readOnly = false) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><DocumentRecipientPanel broadcastGroupId="broadcast-a" groups={[{ id: "group-a", name: "Group A", status: "active" }]} readOnly={readOnly} /></QueryClientProvider>);
}

it("shows all five document lanes and only server-linked passengers, including missing and uncertain", async () => {
  show();
  await screen.findByText("Inside broadcast");
  expect(screen.queryByText("Other broadcast")).not.toBeInTheDocument();
  expect(screen.getByText("Missing document")).toBeInTheDocument();
  expect(screen.getByText("Outcome unknown")).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "Document type" }).children).toHaveLength(5);
  expect(f.preview).toHaveBeenCalledWith("group-a", "visa", "broadcast-a", expect.any(AbortSignal));
  fireEvent.click(screen.getByRole("button", { name: "Shared PDF (1)" }));
  expect(screen.queryByText("Missing document")).not.toBeInTheDocument();
  expect(f.manual).not.toHaveBeenCalled();
  expect(f.unassign).not.toHaveBeenCalled();
});

it("saves a manually selected PDF for the scoped passenger and keeps archived broadcasts read-only", async () => {
  const view = show();
  await screen.findByText("Missing document");
  fireEvent.click(screen.getByRole("button", { name: "Missing document document actions" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "Upload document" }));
  const file = new File(["pdf"], "manual.pdf", { type: "application/pdf" });
  fireEvent.change(screen.getByLabelText("Choose PDF"), { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: "Upload and save" }));
  expect(f.manual).toHaveBeenCalledWith({ passengerId: "missing", file, mode: "add", replacements: [] }, expect.any(Object));
  view.unmount();
  show(true);
  await waitFor(() => expect(screen.getByText("Missing document")).toBeInTheDocument());
  expect(screen.queryByRole("button", { name: /document actions/ })).not.toBeInTheDocument();
  expect(screen.queryByText("Send options for broadcast-a")).not.toBeInTheDocument();
});

it("passes only the checked documents into the scoped send preview", async () => {
  show();
  await screen.findByText("Inside broadcast");
  fireEvent.click(screen.getByRole("checkbox", { name: "Select all assignments for Inside broadcast" }));
  fireEvent.click(screen.getByRole("button", { name: "Send options for broadcast-a" }));
  expect(JSON.parse(screen.getByLabelText("Chosen documents").textContent ?? "{}")).toEqual({ ids: ["doc"], scope: "broadcast-a" });
});

it("shows the latest lane update failure separately from the PDF outcome", async () => {
  f.preview.mockResolvedValue({ recipients: [{ passenger_id: "inside", passenger_name: "Inside broadcast", eligible: true,
    latest_update_status: "failed", latest_update_error: "Provider rejected the update.", latest_update_at: "2026-10-16T00:00:00Z" }] });
  show();
  await screen.findByText("Visa update messages (1)");
  fireEvent.click(screen.getByText("Visa update messages (1)"));
  expect(screen.getByText("Latest update: Failed")).toBeVisible();
  expect(screen.getByText("Provider rejected the update.")).toBeVisible();
  expect(screen.getByText("Outcome unknown")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Refresh update status" })).toBeVisible();
  expect(f.manual).not.toHaveBeenCalled();
});
