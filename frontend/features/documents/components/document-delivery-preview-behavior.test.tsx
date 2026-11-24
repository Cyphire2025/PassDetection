import type { ComponentProps } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DocumentDeliveryPreviewDialog } from "./document-workspace-dialogs";
import { documentPreview } from "./traveller-welcome.test-fixtures";

function props(): ComponentProps<typeof DocumentDeliveryPreviewDialog> {
  return {
    preview: documentPreview(),
    loading: false,
    loadError: null,
    selectedDocumentIds: ["visa-1"],
    resendDocumentIds: [],
    sending: false,
    sendError: null,
    messageContent1: "Your document is attached.",
    messageContent2: "Please review it before departure.",
    onMessageContent1Change: vi.fn(),
    onMessageContent2Change: vi.fn(),
    onToggleDocument: vi.fn(),
    onToggleResend: vi.fn(),
    onClose: vi.fn(),
    onSend: vi.fn(),
    onRefresh: vi.fn(),
  };
}

describe("document delivery preview behavior", () => {
  it("requires a fresh receipt and lets the user refresh before dispatch", () => {
    const input = props();
    input.preview = documentPreview({ preview_token: undefined });
    render(<DocumentDeliveryPreviewDialog {...input} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Refresh the preview");
    const send = screen.getByRole("button", { name: "Send individually to 1" });
    expect(send).toBeDisabled();
    fireEvent.click(send);
    expect(input.onSend).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Refresh preview" }));
    expect(input.onRefresh).toHaveBeenCalledOnce();
  });

  it.each([
    { messageContent1: " \n ", messageContent2: "Keep this text" },
    { messageContent1: "Keep this text", messageContent2: "" },
    { messageContent1: "x".repeat(601), messageContent2: "Keep this text" },
  ])("preserves editable drafts while blocking invalid message content", (draft) => {
    const input = { ...props(), ...draft };
    render(<DocumentDeliveryPreviewDialog {...input} />);
    expect(screen.getByLabelText("Editable text 1")).toHaveValue(draft.messageContent1);
    expect(screen.getByLabelText("Editable text 2")).toHaveValue(draft.messageContent2);
    expect(screen.getByRole("button", { name: "Send individually to 1" })).toBeDisabled();
    expect(input.onSend).not.toHaveBeenCalled();
  });

  it("keeps assigned selection, explicit resend and uncertain exclusion distinct", () => {
    const input = props();
    const preview = documentPreview();
    preview.recipients.push(
      {
        ...preview.recipients[0],
        passenger_id: "sent",
        passenger_name: "Sent traveller",
        document_id: "visa-2",
        delivery_status: "already_sent",
        eligible: false,
        resend_allowed: true
      },
      {
        ...preview.recipients[0],
        passenger_id: "unknown",
        passenger_name: "Uncertain traveller",
        document_id: "visa-3",
        delivery_status: "delivery_unknown",
        eligible: false
      },
      {
        ...preview.recipients[0],
        passenger_id: "unassigned",
        passenger_name: "Unassigned traveller",
        document_id: null,
        eligible: false
      },
    );
    render(<DocumentDeliveryPreviewDialog {...input} preview={preview} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Send document to Mother" }));
    expect(input.onToggleDocument).toHaveBeenCalledExactlyOnceWith("visa-1");
    fireEvent.click(screen.getByRole("button", { name: "Resend" }));
    expect(input.onToggleResend).toHaveBeenCalledExactlyOnceWith("visa-2");
    expect(screen.getByRole("checkbox", { name: "Send document to Uncertain traveller" })).toBeDisabled();
    expect(screen.getByText("Outcome unknown")).toBeVisible();
    expect(screen.queryByText("Unassigned traveller")).not.toBeInTheDocument();
  });

  it("freezes recipient choices while refreshing without losing editable draft callbacks", () => {
    const input = props();
    render(<DocumentDeliveryPreviewDialog {...input} refreshing />);
    expect(screen.getByRole("checkbox", { name: "Send document to Mother" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send individually to 1" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Refreshing" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Editable text 1"), { target: { value: "Updated first text" } });
    fireEvent.change(screen.getByLabelText("Editable text 2"), { target: { value: "Updated second text" } });
    expect(input.onMessageContent1Change).toHaveBeenCalledExactlyOnceWith("Updated first text");
    expect(input.onMessageContent2Change).toHaveBeenCalledExactlyOnceWith("Updated second text");
  });

  it("keeps pending sends inside the modal and restores Escape after settlement", () => {
    const input = props();
    const { rerender } = render(<DocumentDeliveryPreviewDialog {...input} sending />);
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close delivery preview" })).toBeDisabled();
    expect(screen.getByLabelText("Editable text 1")).toBeDisabled();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(input.onClose).not.toHaveBeenCalled();
    rerender(<DocumentDeliveryPreviewDialog {...input} />);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(input.onClose).toHaveBeenCalledOnce();
  });

  it("keeps failed previews unavailable for send while preserving a safe exit", () => {
    const input = props();
    render(<DocumentDeliveryPreviewDialog {...input} preview={undefined} loadError={new Error("Synthetic unavailable preview")} />);
    expect(screen.getAllByText("Synthetic unavailable preview")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Send individually to 1" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(input.onClose).toHaveBeenCalledOnce();
    expect(input.onSend).not.toHaveBeenCalled();
  });
});
