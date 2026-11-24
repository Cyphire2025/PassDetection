import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { QrDeliveryPreview } from "../api/operations.api";
import { QrDeliveryPreviewDialog } from "./tour-group-qr-codes-page";

function recipient(index: number): QrDeliveryPreview["recipients"][number] {
  return {
    passenger_id: `passenger-${index}`, passenger_name: `Synthetic passenger ${index}`, passport_number: null,
    qr_token_id: `token-${index}`, qr_token_version: 1, qr_status: "active", recipient_id: `recipient-${index}`,
    broadcast_group_id: "broadcast", broadcast_name: "Synthetic", phone_number: "+15550000000",
    delivery_id: null, delivery_status: "ready", eligible: true, reason: "Ready", error_message: null, message_preview: null,
  };
}
function props(count = 3) {
  const preview: QrDeliveryPreview = {
    group_id: "group", template_name: "qrcode_v1", template_configured: true, linked_broadcast_count: 1,
    can_send: true, configuration_error: null, message_content: "Travel information",
    summary: { total_passengers: count, ready: count, retryable: 0, already_sent: 0, in_progress: 0, blocked: 0 },
    recipients: Array.from({ length: count }, (_, index) => recipient(index)),
  };
  return { preview, loading: false, loadError: null, qrImages: {}, selectedQrTokenIds: preview.recipients.map(row => row.qr_token_id!),
    messageContent: "Travel information", sending: false, sendError: null, sendFeedback: null,
    onMessageContentChange: vi.fn(), onToggleQr: vi.fn(), onClose: vi.fn(), onSend: vi.fn() };
}

it("indexes selected-token membership once for a 512-row current preview", () => {
  const input = props(512);
  let indexedReads = 0;
  input.selectedQrTokenIds = new Proxy(input.selectedQrTokenIds, {
    get(target, property, receiver) {
      if (typeof property === "string" && /^\d+$/.test(property)) indexedReads++;
      return Reflect.get(target, property, receiver);
    },
  });
  render(<QrDeliveryPreviewDialog {...input} />);
  expect(screen.getAllByRole("checkbox")).toHaveLength(512);
  expect(screen.getAllByRole("checkbox").every(box => (box as HTMLInputElement).checked)).toBe(true);
  expect(screen.getByRole("button", { name: "Send individually to 512" })).toBeEnabled();
  expect(indexedReads, `selected ID indexed reads: ${indexedReads}`).toBeLessThanOrEqual(2048);
});

it("retains selected order/duplicates and eligible row isolation", () => {
  const input = props();
  input.preview.recipients[1] = { ...input.preview.recipients[1], eligible: false, delivery_status: "already_sent" };
  input.preview.recipients[2] = { ...input.preview.recipients[2], qr_token_id: null, eligible: false };
  input.selectedQrTokenIds = ["token-1", "token-0", "token-0"];
  render(<QrDeliveryPreviewDialog {...input} />);
  const boxes = screen.getAllByRole("checkbox");
  expect(boxes[0]).toBeEnabled(); expect(boxes[0]).toBeChecked();
  expect(boxes[1]).toBeDisabled(); expect(boxes[1]).toBeChecked();
  expect(boxes[2]).toBeDisabled(); expect(boxes[2]).not.toBeChecked();
  fireEvent.click(boxes[0]);
  expect(input.onToggleQr).toHaveBeenCalledExactlyOnceWith("token-0");
  expect(input.selectedQrTokenIds).toEqual(["token-1", "token-0", "token-0"]);
  expect(screen.getByRole("button", { name: "Send individually to 3" })).toBeEnabled();
});

it("keeps delivery capability, message and pending gates authoritative", () => {
  const input = props();
  const view = render(<QrDeliveryPreviewDialog {...input} />);
  const send = () => screen.getByRole("button", { name: "Send individually to 3" });
  view.rerender(<QrDeliveryPreviewDialog {...input} preview={{ ...input.preview, can_send: false }} />);
  expect(send()).toBeDisabled();
  view.rerender(<QrDeliveryPreviewDialog {...input} messageContent=" " />);
  expect(send()).toBeDisabled();
  view.rerender(<QrDeliveryPreviewDialog {...input} messageContent={"a".repeat(601)} />);
  expect(send()).toBeDisabled();
  view.rerender(<QrDeliveryPreviewDialog {...input} sending />);
  expect(screen.getByRole("button", { name: "Close QR delivery preview" })).toBeDisabled();
  expect(screen.getAllByRole("checkbox").every(box => (box as HTMLInputElement).disabled)).toBe(true);
});

it("preserves literal message content and bounds its wrapping pane", () => {
  const input = props();
  input.messageContent = `  <script>synthetic</script>\n${"X".repeat(550)}`;
  const { container } = render(<QrDeliveryPreviewDialog {...input} />);
  const text = container.querySelector("p.whitespace-pre-line")!;
  expect(text).toHaveTextContent("<script>synthetic</script>");
  expect(text.textContent).toContain(input.messageContent);
  expect(text).toHaveClass("[overflow-wrap:anywhere]");
  expect(container.querySelector("script")).toBeNull();
  expect(screen.getByRole("textbox", { name: "Editable message" })).toHaveValue(input.messageContent);
});
