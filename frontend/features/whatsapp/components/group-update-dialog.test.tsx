import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GroupUpdateDialog } from "./group-update-dialog";
import { groupUpdatesApi, type GroupUpdatePreview } from "../api/group-updates.api";
import { DocumentBroadcastActions } from "@/features/documents/components/document-broadcast-actions";

const activityMocks = vi.hoisted(() => ({ registerActivity: vi.fn() }));
vi.mock("./whatsapp-activity-tracker", () => ({ useWhatsAppActivityTracker: () => activityMocks }));
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
function mount(broadcastGroupId?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><GroupUpdateDialog groupId="trip" groupName="Test trip" broadcastGroupId={broadcastGroupId} onClose={vi.fn()} /></QueryClientProvider>);
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
  expect(screen.getByLabelText("Document type")).toBeEnabled();
  expect(screen.getByRole("button", { name: "Send individually to 2" })).toBeDisabled();
});

it("combines filters, supports every flight lane and resets selection on audience change", async () => {
  mount();
  await screen.findByText("3 people · 2 WhatsApp messages");
  fireEvent.click(screen.getByRole("button", { name: "Clear" }));
  fireEvent.click(screen.getByRole("radio", { name: "Document submission: Not submitted" }));
  fireEvent.click(screen.getByRole("radio", { name: "Document distribution: Pending" }));
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
  fireEvent.click(screen.getByRole("button", { name: "Clear" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Select Imported contact" }));
  fireEvent.change(screen.getByLabelText("Your update message"), { target: { value: "Please\n\nsubmit\tyour documents." } });
  expect(screen.getByTestId("whatsapp-message-preview")).toHaveTextContent("Please submit your documents.");
  fireEvent.click(screen.getByRole("button", { name: "Send individually to 1" }));
  await screen.findByText("Queued one update.");
  expect(groupUpdatesApi.send).toHaveBeenCalledWith("trip", expect.objectContaining({ audience_keys: ["contact:1"], message_content: "Please submit your documents.", preview_token: initial.preview_token }));
});

it("registers every returned update batch with the shared progress tracker", async () => {
  vi.mocked(groupUpdatesApi.send).mockResolvedValue({ request_id: "request", queued_count: 2, passenger_count: 3,
    message: "Updates queued.", batches: [
      { batch_id: "batch-one", broadcast_group_id: "broadcast", queued_count: 1 },
      { batch_id: "batch-two", broadcast_group_id: "another", queued_count: 1 },
    ] });
  mount();
  await screen.findByText("3 people · 2 WhatsApp messages");
  fireEvent.change(screen.getByLabelText("Your update message"), { target: { value: "Your documents are being processed." } });
  fireEvent.click(screen.getByRole("button", { name: "Send individually to 2" }));
  await screen.findByText("Updates queued.");
  expect(activityMocks.registerActivity).toHaveBeenCalledTimes(2);
  expect(activityMocks.registerActivity).toHaveBeenCalledWith(expect.objectContaining({
    id: "batch-one", kind: "broadcast", messageType: "document_update", title: "Update message broadcast",
    contextLabel: "Test trip", sourceGroupId: "broadcast", total: 1, queued: 1,
  }));
  expect(activityMocks.registerActivity).toHaveBeenCalledWith(expect.objectContaining({ id: "batch-two", sourceGroupId: "another" }));
});

it("freezes the exact request after a network uncertainty and retries without a new request id", async () => {
  vi.mocked(groupUpdatesApi.send).mockRejectedValueOnce({ message: "Connection interrupted" }).mockResolvedValueOnce({ request_id: "request", queued_count: 2, passenger_count: 3, message: "Already queued." });
  mount();
  await screen.findByText("3 people · 2 WhatsApp messages");
  fireEvent.change(screen.getByLabelText("Your update message"), { target: { value: "Please wait." } });
  fireEvent.click(screen.getByRole("button", { name: "Send individually to 2" }));
  const retry = await screen.findByRole("button", { name: "Retry same request" });
  expect(screen.getByRole("radio", { name: "Document submission: All" })).toBeDisabled();
  expect(screen.getByLabelText("Your update message")).toBeDisabled();
  fireEvent.click(retry);
  await screen.findByText("Already queued.");
  expect(vi.mocked(groupUpdatesApi.send).mock.calls[1][1]).toEqual(vi.mocked(groupUpdatesApi.send).mock.calls[0][1]);
});

it("blocks sending while the audience is still loading", async () => {
  vi.mocked(groupUpdatesApi.preview).mockImplementation(() => new Promise(() => {}));
  mount();
  fireEvent.change(screen.getByLabelText("Your update message"), { target: { value: "Wait." } });
  expect(screen.getByRole("button", { name: "Send individually to 0" })).toBeDisabled();
  expect(groupUpdatesApi.send).not.toHaveBeenCalled();
});

it("document distribution opens document sending directly without an update option", () => {
  const open = vi.fn();
  render(<DocumentBroadcastActions groupId="trip" documentType="visa" onSendDocuments={open} />);
  fireEvent.click(screen.getByRole("button", { name: "Send WhatsApp Broadcast" }));
  expect(open).toHaveBeenCalledOnce();
  expect(screen.queryByText("Inform / update")).not.toBeInTheDocument();
});

it("keeps all 84 earlier update attempts unchecked when opening, changing filters or refreshing", async () => {
  const statuses = ["read", "delivered", "sent", "submitted", "failed", "delivery_unknown", "queued", "processing"];
  const recipients = Array.from({ length: 88 }, (_, index) => ({
    ...initial.recipients[0], audience_key: `person:${index}`, name: `Person ${index}`,
    phone_number: `+91900000${String(index).padStart(4, "0")}`, latest_update_status: index < 84 ? statuses[index % statuses.length] : null,
    eligible: index >= 84 || !["delivery_unknown", "queued", "processing"].includes(statuses[index % statuses.length]),
  }));
  vi.mocked(groupUpdatesApi.preview).mockImplementation(async (_id, audience) => ({ ...initial, audience, recipients }));
  mount();
  await screen.findByText("4 people · 4 WhatsApp messages");
  expect(screen.getByText(/84 earlier update attempts saved/)).toBeInTheDocument();
  for (const box of screen.getAllByRole("checkbox")) expect(box).not.toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(screen.getByRole("checkbox", { name: "Select Person 84" })).toBeChecked();
  fireEvent.click(screen.getByRole("radio", { name: "Document submission: Submitted" }));
  fireEvent.click(screen.getByRole("radio", { name: "Document distribution: Pending" }));
  await screen.findByText("4 people · 4 WhatsApp messages");
  fireEvent.click(screen.getByRole("button", { name: "Refresh preview" }));
  await screen.findByText("4 people · 4 WhatsApp messages");
  expect(screen.getByRole("checkbox", { name: "Select Person 0" })).not.toBeChecked();
  expect(groupUpdatesApi.send).not.toHaveBeenCalled();
});

it("allows an explicit selection of earlier completed or failed updates without auto-selecting them", async () => {
  const recipients = initial.recipients.map((row, index) => ({ ...row, latest_update_status: index === 0 ? "read" : index === 1 ? "failed" : null }));
  vi.mocked(groupUpdatesApi.preview).mockImplementation(async (_id, audience) => ({ ...initial, audience, recipients }));
  vi.mocked(groupUpdatesApi.send).mockResolvedValue({ request_id: "request", queued_count: 2, passenger_count: 3, message: "Queued explicitly." });
  mount();
  await screen.findByText("1 people · 1 WhatsApp messages");
  expect(screen.getByRole("checkbox", { name: "Select Submitted person" })).not.toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "Select all" }));
  expect(screen.getByRole("checkbox", { name: "Select Submitted person" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Select Imported contact" })).toBeChecked();
  fireEvent.change(screen.getByLabelText("Your update message"), { target: { value: "A different update." } });
  fireEvent.click(screen.getByRole("button", { name: "Send individually to 2" }));
  await screen.findByText("Queued explicitly.");
  expect(groupUpdatesApi.send).toHaveBeenCalledWith("trip", expect.objectContaining({ audience_keys: ["contact:0", "contact:1", "contact:2"] }));
});

it("keeps other broadcasts out of the preview and send selection", async () => {
  const recipients = initial.recipients.map((row, index) => ({ ...row, broadcast_group_id: index === 0 ? "chosen" : "another" }));
  vi.mocked(groupUpdatesApi.preview).mockImplementation(async (_id, audience) => ({ ...initial, audience, recipients }));
  vi.mocked(groupUpdatesApi.send).mockResolvedValue({ request_id: "request", queued_count: 1, passenger_count: 1, message: "Queued for this broadcast." });
  mount("chosen");
  await screen.findByText("1 people · 1 WhatsApp messages");
  expect(screen.queryByRole("checkbox", { name: "Select Imported contact" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Your update message"), { target: { value: "Update." } });
  fireEvent.click(screen.getByRole("button", { name: "Send individually to 1" }));
  await screen.findByText("Queued for this broadcast.");
  expect(groupUpdatesApi.send).toHaveBeenCalledWith("trip", expect.objectContaining({ audience_keys: ["contact:0"] }));
});
