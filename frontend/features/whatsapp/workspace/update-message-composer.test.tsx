import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";
import { groupUpdatesApi, type GroupUpdatePreview } from "../api/group-updates.api";
import { UpdateMessageComposer } from "./update-message-composer";

const mocks = vi.hoisted(() => ({ push: vi.fn(), registerActivity: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("../components/whatsapp-activity-tracker", () => ({ useWhatsAppActivityTracker: () => mocks }));
vi.mock("./broadcast-workspace-shell", () => ({ useBroadcast: () => ({
  id: "broadcast", name: "Synthetic trip", linked_client_groups: [{ id: "trip", status: "active" }],
} as WhatsAppBroadcastGroupDetail) }));
vi.mock("../api/group-updates.api", () => ({ groupUpdatesApi: { preview: vi.fn(), send: vi.fn() } }));

const preview: GroupUpdatePreview = {
  group_id: "trip", audience: { submission_status: "all", document_status: "all", document_type: "visa" },
  preview_token: "synthetic-preview", can_send: true, configuration_error: null,
  template_name: "pending_v1", template_language: "en",
  recipients: [{ audience_key: "contact:one", name: "Synthetic person", recipient_id: "one",
    broadcast_group_id: "broadcast", passenger_id: "person", phone_number: "+919000000001",
    phone_source: "submitted", submission_status: "submitted", document_count: 1, confirmed_count: 1,
    eligible: true, reason: null, latest_update_status: null, latest_update_at: null }],
};
const result = { request_id: "retained", queued_count: 1, passenger_count: 1, message: "Queued." };
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: 2 } } });
  const view = render(<QueryClientProvider client={client}><UpdateMessageComposer /></QueryClientProvider>);
  return { ...view, client };
}
async function review() {
  await screen.findByRole("checkbox", { name: "Select Synthetic person" });
  fireEvent.change(screen.getByRole("textbox", { name: /Update message/ }), { target: { value: "Meet at the lobby." } });
  fireEvent.click(screen.getByRole("button", { name: "Review message" }));
  return screen.getByRole("button", { name: "Send 1 messages" });
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(groupUpdatesApi.preview).mockResolvedValue(preview);
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

it("admits one current trip update before React commits the pending state", async () => {
  vi.mocked(groupUpdatesApi.send).mockImplementation(() => new Promise(() => {}));
  mount();
  const button = await review();
  act(() => { button.click(); button.click(); });
  await waitFor(() => expect(groupUpdatesApi.send).toHaveBeenCalledTimes(1));
});

it("checks the exact uncertain request and stops after its acknowledgement", async () => {
  vi.mocked(groupUpdatesApi.send).mockRejectedValueOnce({ message: "Connection interrupted" }).mockResolvedValue(result);
  mount();
  fireEvent.click(await review());
  const retry = await screen.findByRole("button", { name: "Check same send request" });
  expect(groupUpdatesApi.send).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("textbox", { name: /Update message/ })).toBeDisabled();
  fireEvent.click(retry);
  await waitFor(() => expect(groupUpdatesApi.send).toHaveBeenCalledTimes(2));
  expect(vi.mocked(groupUpdatesApi.send).mock.calls[1][1]).toEqual(vi.mocked(groupUpdatesApi.send).mock.calls[0][1]);
  await waitFor(() => expect(screen.getByRole("button", { name: "Send 1 messages" })).toBeDisabled());
});

it("stops interval polling when a cached queued audience is denied", async () => {
  vi.useFakeTimers();
  vi.mocked(groupUpdatesApi.preview).mockResolvedValueOnce({ ...preview,
    recipients: [{ ...preview.recipients[0], latest_update_status: "queued" }],
  }).mockRejectedValue({ status: 403, code: "FORBIDDEN" });
  const view = mount();
  try {
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    await act(async () => { await vi.advanceTimersByTimeAsync(5_001); });
    expect(groupUpdatesApi.preview).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(groupUpdatesApi.preview).toHaveBeenCalledTimes(2);
    vi.mocked(groupUpdatesApi.preview).mockResolvedValue(preview);
    fireEvent.click(screen.getByRole("button", { name: "Refresh preview" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(groupUpdatesApi.preview).toHaveBeenCalledTimes(3);
  } finally { view.unmount(); view.client.clear(); }
});
