import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DocumentUpdateDialog } from "./document-update-dialog";
import { documentUpdatesApi, type DocumentUpdatePreview } from "../api/document-updates.api";

vi.mock("../api/document-updates.api", () => ({ documentUpdatesApi: { preview: vi.fn(), send: vi.fn() } }));

const preview: DocumentUpdatePreview = {
  group_id: "trip", document_type: "visa", preview_token: "a".repeat(64),
  template_name: "pending_v1", template_language: "en", can_send: true, configuration_error: null,
  recipients: ["Missing", "Unknown", "Sent", "Shared"].map((name, index) => ({
    passenger_id: name, passenger_name: name, phone_number: index === 3 ? "+911" : `+91${index}`,
    recipient_id: `r${index}`, broadcast_group_id: "broadcast", document_count: index === 0 ? 0 : 1,
    confirmed_count: index === 2 ? 1 : 0, eligible: index !== 2,
    reason: index === 2 ? "All assigned documents have a confirmed send." : null, latest_update_status: null,
  })),
};
function mount() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><DocumentUpdateDialog groupId="trip" documentType="visa" broadcastGroupId="broadcast" onClose={vi.fn()} /></QueryClientProvider>);
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(documentUpdatesApi.preview).mockResolvedValue(preview); });
afterEach(cleanup);

it("selects missing and unknown documents, excludes confirmed sends, and counts shared phones once", async () => {
  mount();
  expect(await screen.findByRole("checkbox", { name: "Select Missing" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Select Unknown" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Select Sent" })).toBeDisabled();
  expect(screen.getByRole("checkbox", { name: "Select Sent" })).not.toBeChecked();
  expect(screen.getByText("3 travellers · 2 WhatsApp messages")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Send update to 2" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Your update message"), { target: { value: "Your visas are being processed." } });
  vi.mocked(documentUpdatesApi.send).mockResolvedValue({ request_id: "request", queued_count: 2, passenger_count: 3, message: "Queued updates." });
  fireEvent.click(screen.getByRole("button", { name: "Send update to 2" }));
  await screen.findByText("Queued updates.");
  expect(documentUpdatesApi.send).toHaveBeenCalledWith("trip", "visa", expect.objectContaining({
    passenger_ids: ["Missing", "Unknown", "Shared"], broadcast_group_id: "broadcast",
    message_content: "Your visas are being processed.", preview_token: preview.preview_token,
  }));
});

it("retries the exact request after a lost acknowledgement and freezes edits until resolved", async () => {
  vi.mocked(documentUpdatesApi.send).mockRejectedValueOnce({ message: "Network interrupted" }).mockResolvedValueOnce({
    request_id: "request", queued_count: 2, passenger_count: 3, message: "Request already queued.",
  });
  mount();
  await screen.findByRole("checkbox", { name: "Select Missing" });
  fireEvent.change(screen.getByLabelText("Your update message"), { target: { value: "Please wait for your visa." } });
  fireEvent.click(screen.getByRole("button", { name: "Send update to 2" }));
  const retry = await screen.findByRole("button", { name: "Retry same request" });
  expect(screen.getByLabelText("Your update message")).toBeDisabled();
  fireEvent.click(retry);
  await screen.findByText("Request already queued.");
  const calls = vi.mocked(documentUpdatesApi.send).mock.calls;
  expect(calls[1][2]).toEqual(calls[0][2]);
});

it("allows refreshed selection after a definite stale-preview rejection", async () => {
  vi.mocked(documentUpdatesApi.send).mockRejectedValue({ status: 409, message: "Audience changed." });
  mount();
  await screen.findByRole("checkbox", { name: "Select Missing" });
  fireEvent.change(screen.getByLabelText("Your update message"), { target: { value: "Please wait." } });
  fireEvent.click(screen.getByRole("button", { name: "Send update to 2" }));
  await screen.findByText("Audience changed.");
  expect(screen.getByLabelText("Your update message")).not.toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Refresh preview" }));
  await waitFor(() => expect(documentUpdatesApi.preview).toHaveBeenCalledTimes(2));
});

it("displays the latest update failure reason and timestamp", async () => {
  vi.mocked(documentUpdatesApi.preview).mockResolvedValue({ ...preview, recipients: [{ ...preview.recipients[0],
    latest_update_status: "failed", latest_update_error: "This update was rejected by WhatsApp.", latest_update_at: "2026-10-16T00:00:00Z" }] });
  const view = mount();
  expect(await screen.findByText("Latest update: Failed")).toBeInTheDocument();
  expect(screen.getByText("This update was rejected by WhatsApp.")).toBeInTheDocument();
  expect(view.container.querySelector("time")?.dateTime).toBe("2026-10-16T00:00:00Z");
  expect(documentUpdatesApi.send).not.toHaveBeenCalled();
});
