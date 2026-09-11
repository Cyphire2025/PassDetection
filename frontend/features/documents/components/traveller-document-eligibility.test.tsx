import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { activeDeliverySelection } from "./document-workspace-model";
import { DocumentDeliveryPreviewDialog } from "./document-workspace-dialogs";
import { eligibleWelcomePhones, selectedWelcomePhones } from "./traveller-welcome-model";
import { documentPreview, welcomeRecipient } from "./traveller-welcome.test-fixtures";

describe("traveller document eligibility", () => {
  it("drops stale selections and resends when a changed phone needs welcoming", () => {
    expect(activeDeliverySelection(documentPreview(), ["visa-1"], ["visa-1"]))
      .toEqual({ documentIds: [], resendDocumentIds: [] });
  });

  it("fails closed if a row is marked eligible but still requires welcome", () => {
    const data = documentPreview();
    data.recipients[0].eligible = true;
    expect(activeDeliverySelection(data, ["visa-1"], [])).toEqual({ documentIds: [], resendDocumentIds: [] });
  });

  it("allows documents after confirmed welcome and preserves explicit resend requirements", () => {
    const data = documentPreview();
    Object.assign(data.recipients[0], { eligible: true, welcome_required: false, welcome_status: "delivered", delivery_status: "ready" });
    expect(activeDeliverySelection(data, null, []).documentIds).toEqual(["visa-1"]);
    Object.assign(data.recipients[0], { eligible: false, delivery_status: "already_sent", resend_allowed: true });
    expect(activeDeliverySelection(data, ["visa-1"], []).documentIds).toEqual([]);
    expect(activeDeliverySelection(data, ["visa-1"], ["visa-1"]).resendDocumentIds).toEqual(["visa-1"]);
  });

  it("deduplicates welcome destinations and requires a rendered message", () => {
    expect(eligibleWelcomePhones([welcomeRecipient(), welcomeRecipient(), welcomeRecipient({ phone_number: "+919900000009", rendered_message: null })])).toEqual(["+919900000001"]);
  });

  it("bounds large welcome selections and leaves remaining numbers ready for the next send", () => {
    const phones = Array.from({ length: 1_501 }, (_, index) => String(index));
    expect(selectedWelcomePhones(phones, null)).toHaveLength(1_500);
    expect(selectedWelcomePhones([phones[1_500]], null)).toEqual([phones[1_500]]);
    expect(selectedWelcomePhones(phones, ["stale", "1", "1"])).toEqual(["1"]);
  });

  it("shows submitted destination, disabled document and a direct path to welcome review", () => {
    const onReviewWelcomes = vi.fn();
    render(<DocumentDeliveryPreviewDialog preview={documentPreview()} loading={false} loadError={null} selectedDocumentIds={[]} resendDocumentIds={[]} sending={false} sendError={null} messageContent1="Visa attached" messageContent2="Have a good trip" onMessageContent1Change={vi.fn()} onMessageContent2Change={vi.fn()} onToggleDocument={vi.fn()} onToggleResend={vi.fn()} onClose={vi.fn()} onSend={vi.fn()} onReviewWelcomes={onReviewWelcomes} />);
    expect(screen.getByText("+919900000001")).toBeVisible();
    expect(screen.getByText("Entered for this traveller")).toBeVisible();
    expect(screen.getByText("Welcome needed")).toBeVisible();
    expect(screen.getByRole("checkbox", { name: "Send document to Mother" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send individually to 0" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Review traveller welcomes" }));
    expect(onReviewWelcomes).toHaveBeenCalledOnce();
  });
});
