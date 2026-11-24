import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { QrDeliveryPreviewDialog } from "./tour-group-qr-codes-page";

function preview(sending = false) {
  return {
    preview: undefined, loading: false, loadError: null, qrImages: {}, selectedQrTokenIds: [],
    messageContent: "Travel information", sending, sendError: null, sendFeedback: null,
    onMessageContentChange: vi.fn(), onToggleQr: vi.fn(), onClose: vi.fn(), onSend: vi.fn(),
  };
}

describe("QR delivery preview keyboard isolation", () => {
  it("inerts the background, contains external focus and restores the trigger after dismissal", () => {
    const trigger = document.createElement("button");
    trigger.textContent = "Open delivery preview";
    document.body.append(trigger);
    trigger.focus();
    const props = preview();
    const view = render(<QrDeliveryPreviewDialog {...props} />);
    const close = screen.getByRole("button", { name: "Close QR delivery preview" });
    expect(close).toHaveFocus();
    expect(trigger).toHaveAttribute("inert");
    trigger.focus();
    expect(close).toHaveFocus();
    fireEvent.keyDown(close, { key: "Escape" });
    expect(props.onClose).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(trigger).not.toHaveAttribute("inert");
    expect(trigger).toHaveFocus();
    trigger.remove();
  });

  it("keeps a pending send open and uses the current dismissal state after it settles", () => {
    const props = preview(true);
    const view = render(<QrDeliveryPreviewDialog {...props} />);
    const close = screen.getByRole("button", { name: "Close QR delivery preview" });
    expect(close).toBeDisabled();
    fireEvent.keyDown(close, { key: "Escape" });
    expect(props.onClose).not.toHaveBeenCalled();
    view.rerender(<QrDeliveryPreviewDialog {...props} sending={false} />);
    fireEvent.keyDown(close, { key: "Escape" });
    expect(props.onClose).toHaveBeenCalledTimes(1);
    expect(props.onSend).not.toHaveBeenCalled();
  });
});
