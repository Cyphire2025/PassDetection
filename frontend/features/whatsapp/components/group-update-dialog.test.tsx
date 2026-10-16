import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GroupUpdateDialog } from "./group-update-dialog";
import { groupUpdatesApi, type GroupUpdatePreview } from "../api/group-updates.api";
import { DocumentBroadcastActions } from "@/features/documents/components/document-broadcast-actions";

vi.mock("../api/group-updates.api", () => ({ groupUpdatesApi: { preview: vi.fn(), send: vi.fn() } }));
const initial: GroupUpdatePreview = {
  group_id: "trip", audience: { submission_status: "all", document_status: "all", document_type: "visa" },
  preview_token: "a".repeat(64), template_name: "pending_v1", template_language: "en", can_send: true, configuration_error: null,
  recipients: ["Submitted person", "Imported contact", "Shared number", "Needs review"].map((name, i) => ({
    audience_key: `contact:${i}`, name, recipient_id: `r${i}`, broadcast_group_id: "broadcast", passenger_id: i === 1 ? null : `p${i}`,
    phone_number: i === 2 ? "+919123456700" : `+9191234567${i}0`, phone_source: i === 1 ? "imported" : "submitted",
    submission_status: i === 1 ? "not_submitted" : "submitted", document_count: 1, confirmed_count: i === 0 ? 1 : 0,
    eligible: i !== 3, reason: i === 3 ? "Review the submitted contact." : null, latest_update_status: null, latest_update_at: null,
  })),
};
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><GroupUpdateDialog groupId="trip" groupName="Test trip" onClose={vi.fn()} /></QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(groupUpdatesApi.preview).mockImplementation(async (_id, audience) => ({ ...initial, audience }));
});
afterEach(cleanup);

it("opens with both audiences combined, shows phone sources and counts shared numbers once", async () => {
  mount();
  expect(await screen.findByText("3 people · 2 WhatsApp messages")).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "Select Submitted person" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Select Imported contact" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Select Needs review" })).toBeDisabled();
  expect(screen.getByText(/Imported broadcast number · Not submitted/)).toBeInTheDocument();
  expect(screen.getByLabelText("Document type")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Send update to 2" })).toBeDisabled();
});

it("combines filters, supports every flight lane and resets selection on audience change", async () => {
  mount();
  await screen.findByText("3 people · 2 WhatsApp messages");
  fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
  fireEvent.change(screen.getByLabelText("Submission status"), { target: { value: "not_submitted" } });
  fireEvent.change(screen.getByLabelText("Document delivery"), { target: { value: "pending" } });
  expect(screen.getByLabelText("Document type")).toBeEnabled();
  for (const lane of ["flight_ticket", "flight_ticket_arrival", "flight_ticket_domestic", "flight_ticket_domestic_arrival"]) {
    fireEvent.change(screen.getByLabelText("Document type"), { target: { value: lane } });
    await waitFor(() => expect(groupUpdatesApi.preview).toHaveBeenCalledWith("trip", { submission_status: "not_submitted", document_status: "pending", document_type: lane }, expect.any(AbortSignal)));
  }
  await screen.findByText("3 people · 2 WhatsApp messages");
});

it("previews normalized paragraphs and sends only the selected people", async () => {
  vi.mocked(groupUpdatesApi.send).mockResolvedValue({ request_id: "request", queued_count: 1, passenger_count: 1, message: "Queued one update." });
  mount();
  await screen.findByText("3 people · 2 WhatsApp messages");
  fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Select Imported contact" }));
  fireEvent.change(screen.getByLabelText("Your update message"), { target: { value: "Please\n\nsubmit\tyour documents." } });
  expect(screen.getByTestId("group-update-message-preview")).toHaveTextContent("Please submit your documents.");
  fireEvent.click(screen.getByRole("button", { name: "Send update to 1" }));
  await screen.findByText("Queued one update.");
  expect(groupUpdatesApi.send).toHaveBeenCalledWith("trip", expect.objectContaining({ audience_keys: ["contact:1"], message_content: "Please submit your documents.", preview_token: initial.preview_token }));
});

it("freezes the exact request after a network uncertainty and retries without a new request id", async () => {
  vi.mocked(groupUpdatesApi.send).mockRejectedValueOnce({ message: "Connection interrupted" }).mockResolvedValueOnce({ request_id: "request", queued_count: 2, passenger_count: 3, message: "Already queued." });
  mount();
  await screen.findByText("3 people · 2 WhatsApp messages");
  fireEvent.change(screen.getByLabelText("Your update message"), { target: { value: "Please wait." } });
  fireEvent.click(screen.getByRole("button", { name: "Send update to 2" }));
  const retry = await screen.findByRole("button", { name: "Retry same request" });
  expect(screen.getByLabelText("Submission status")).toBeDisabled();
  expect(screen.getByLabelText("Your update message")).toBeDisabled();
  fireEvent.click(retry);
  await screen.findByText("Already queued.");
  expect(vi.mocked(groupUpdatesApi.send).mock.calls[1][1]).toEqual(vi.mocked(groupUpdatesApi.send).mock.calls[0][1]);
});

it("blocks sending while the audience is still loading", async () => {
  vi.mocked(groupUpdatesApi.preview).mockImplementation(() => new Promise(() => {}));
  mount();
  fireEvent.change(screen.getByLabelText("Your update message"), { target: { value: "Wait." } });
  expect(screen.getByRole("button", { name: "Send update to 0" })).toBeDisabled();
  expect(groupUpdatesApi.send).not.toHaveBeenCalled();
});

it("document distribution opens document sending directly without an update option", () => {
  const open = vi.fn();
  render(<DocumentBroadcastActions groupId="trip" documentType="visa" onSendDocuments={open} />);
  fireEvent.click(screen.getByRole("button", { name: "Send WhatsApp Broadcast" }));
  expect(open).toHaveBeenCalledOnce();
  expect(screen.queryByText("Inform / update")).not.toBeInTheDocument();
});
