import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TravellerWelcomeDialog } from "./traveller-welcome-dialog";
import { welcomePreview, welcomeRecipient } from "./traveller-welcome.test-fixtures";

function props() {
  return { preview: welcomePreview(), loading: false, refreshing: false, loadError: null, sending: false, sendError: null, onSourceChange: vi.fn(), onRefresh: vi.fn(), onClose: vi.fn(), onSend: vi.fn() };
}

describe("traveller welcome review", () => {
  it("preselects only new eligible numbers and sends one welcome for a shared family phone", () => {
    const data = props();
    render(<TravellerWelcomeDialog {...data} />);
    expect(screen.getByRole("dialog", { name: "Welcome new traveller numbers" })).toBeVisible();
    expect(screen.getByText("Hello Mother and Father, welcome to the company trip.")).toBeVisible();
    expect(screen.getByRole("checkbox", { name: "Welcome +919900000001" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Welcome +919900000002" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Welcome +919900000003" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Send welcome to 1 number" }));
    expect(data.onSend).toHaveBeenCalledExactlyOnceWith(["+919900000001"]);
  });

  it("requires an explicit selected number and excludes it once refreshed as welcomed", () => {
    const data = props();
    const { rerender } = render(<TravellerWelcomeDialog {...data} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Welcome +919900000001" }));
    expect(screen.getByRole("button", { name: "Send welcome to 0 numbers" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Welcome +919900000001" }));
    rerender(<TravellerWelcomeDialog {...data} preview={welcomePreview({ recipients: [welcomeRecipient({ status: "delivered", eligible: false })] })} />);
    expect(screen.getByRole("button", { name: "Send welcome to 0 numbers" })).toBeDisabled();
    expect(data.onSend).not.toHaveBeenCalled();
  });

  it.each(["refreshing", "sending", "loading"] as const)("blocks sending while %s", (state) => {
    const data = props();
    render(<TravellerWelcomeDialog {...data} {...{ [state]: true }} />);
    expect(screen.getByRole("button", { name: /Send welcome to/ })).toBeDisabled();
  });

  it("keeps server configuration failures and missing numbers actionable", () => {
    render(<TravellerWelcomeDialog {...props()} preview={welcomePreview({ can_send: false, configuration_error: "Choose an available welcome image.", recipients: [welcomeRecipient({ phone_number: null, eligible: false, rendered_message: null, status: "blocked", reason: "Enter the traveller's WhatsApp number." })] })} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Choose an available welcome image.");
    expect(screen.getByText("Enter the traveller's WhatsApp number.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Send welcome to 0 numbers" })).toBeDisabled();
  });

  it("offers a source selector only when multiple linked broadcasts exist", () => {
    const data = props();
    const { rerender } = render(<TravellerWelcomeDialog {...data} />);
    expect(screen.queryByLabelText("Welcome message from")).toBeNull();
    rerender(<TravellerWelcomeDialog {...data} preview={welcomePreview({ sources: [{ id: "source", name: "First" }, { id: "second", name: "Second" }] })} />);
    fireEvent.change(screen.getByLabelText("Welcome message from"), { target: { value: "second" } });
    expect(data.onSourceChange).toHaveBeenCalledExactlyOnceWith("second");
  });

  it("supports optional image recovery and prevents sending while it uploads", () => {
    const data = props();
    const replace = vi.fn();
    const { rerender } = render(<TravellerWelcomeDialog {...data} onReplaceImage={replace} />);
    const image = new File(["image"], "welcome.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Replace welcome image (optional)"), { target: { files: [image] } });
    expect(replace).toHaveBeenCalledExactlyOnceWith(image);
    rerender(<TravellerWelcomeDialog {...data} onReplaceImage={replace} imageUploading />);
    expect(screen.getByRole("button", { name: "Send welcome to 1 number" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
  });

  it("lets the operator revert an accidental welcome-image replacement", () => {
    const reset = vi.fn();
    render(<TravellerWelcomeDialog {...props()} onUseOriginalImage={reset} />);
    fireEvent.click(screen.getByRole("button", { name: "Use original image" }));
    expect(reset).toHaveBeenCalledOnce();
  });
});
