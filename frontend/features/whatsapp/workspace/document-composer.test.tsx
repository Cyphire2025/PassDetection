import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import type { DocumentDeliveryPreview, SendDocumentBroadcastResult } from "@/types/document-distribution.types";
import { documentDistributionApi } from "@/features/documents/api/document-distribution.api";
import { BroadcastDocumentComposer } from "./document-composer";

const mocks = vi.hoisted(() => ({ registerActivity: vi.fn() }));
vi.mock("../components/whatsapp-activity-tracker", () => ({ useWhatsAppActivityTracker: () => mocks }));
vi.mock("./broadcast-workspace-shell", () => ({ useBroadcast: () => ({ id: "broadcast", name: "Synthetic trip" }) }));
vi.mock("@/features/documents/api/document-distribution.api", () => ({ documentDistributionApi: {
  previewWhatsAppDelivery: vi.fn(), sendWhatsAppDelivery: vi.fn(),
} }));
const sources = [{ id: "first", name: "First source" }, { id: "second", name: "Second source" }];
const owner = { id: "staff-a", role: "agency_admin", agency_id: "agency" } as User;
const receipt: SendDocumentBroadcastResult = { send_batch_id: "accepted", queued_count: 1, skipped_count: 0, message: "Queued." };
function preview(groupId: string): DocumentDeliveryPreview {
  return { group_id: groupId, batch_id: `batch-${groupId}`, preview_token: `token-${groupId}`,
    template_configured: true, message_content_1: "Review your document.", message_content_2: "Reply with corrections.",
    recipients: [{ passenger_id: `person-${groupId}`, passenger_name: `Synthetic ${groupId}`, document_id: `document-${groupId}`,
      document_filename: `${groupId}.pdf`, broadcast_group_id: "broadcast", eligible: true, delivery_status: "ready" }],
  } as DocumentDeliveryPreview;
}
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn();
  const view = render(<QueryClientProvider client={client}>
    <BroadcastDocumentComposer documentType="visa" sources={sources} onClose={onClose} />
  </QueryClientProvider>);
  return { ...view, onClose };
}
async function review() {
  await waitFor(() => expect(screen.getByRole("button", { name: "Review message" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Review message" }));
  return screen.getByRole("button", { name: "Send 2 messages" });
}
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: owner, isAuthenticated: true });
  vi.mocked(documentDistributionApi.previewWhatsAppDelivery).mockImplementation(async groupId => preview(groupId));
  vi.mocked(documentDistributionApi.sendWhatsAppDelivery).mockResolvedValue(receipt);
});
afterEach(cleanup);

it("binds both document preview and dispatch to the broadcast being reviewed", async () => {
  mount();
  fireEvent.click(await review());
  await waitFor(() => expect(documentDistributionApi.sendWhatsAppDelivery).toHaveBeenCalledTimes(2));
  for (const source of sources) {
    expect(documentDistributionApi.previewWhatsAppDelivery).toHaveBeenCalledWith(source.id, "visa", expect.any(AbortSignal), "broadcast");
    expect(documentDistributionApi.sendWhatsAppDelivery).toHaveBeenCalledWith(`batch-${source.id}`, [`document-${source.id}`], [],
      "Review your document.", "Reply with corrections.", `token-${source.id}`, "broadcast");
  }
});

it("does not continue a multi-source document send under a replacement account", async () => {
  let release!: (value: SendDocumentBroadcastResult) => void;
  vi.mocked(documentDistributionApi.sendWhatsAppDelivery).mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
  const view = mount();
  fireEvent.click(await review());
  await waitFor(() => expect(documentDistributionApi.sendWhatsAppDelivery).toHaveBeenCalledTimes(1));
  useAuthStore.setState({ user: { ...owner, id: "staff-b" } });
  await act(async () => { release(receipt); });
  await screen.findByRole("alert");
  expect(documentDistributionApi.sendWhatsAppDelivery).toHaveBeenCalledTimes(1);
  expect(mocks.registerActivity).not.toHaveBeenCalled();
  expect(view.onClose).not.toHaveBeenCalled();
});
