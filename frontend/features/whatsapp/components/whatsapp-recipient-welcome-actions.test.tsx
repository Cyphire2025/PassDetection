import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { WhatsAppRecipient } from "../api/whatsapp.api";
import { ActiveRecipientRow } from "./whatsapp-active-recipient-row";

const status = (messageType: string, delivered: boolean) => ({ message_type: messageType, status: delivered ? "delivered" : "failed", already_sent: delivered, latest_resend_status: null, resend_blocked: false, submitted_at: null, status_updated_at: "2026-09-12T00:00:00Z" });

function renderRow(delivered: boolean, messageTypes = ["welcome", "passport_link"]) {
  const recipient: WhatsAppRecipient = { id: "contact", name: "Alex", phone_number: "+919900000001", normalized_phone_number: "+919900000001", imported_fields: {}, welcome_status: delivered ? "delivered" : "required", welcome_delivered: delivered, welcome_required_reason: delivered ? null : "Welcome must arrive before passport links.", message_statuses: [status("welcome", delivered), status("passport_link", false), status("group_invite", false)] };
  const onResend = vi.fn();
  render(<table><tbody><ActiveRecipientRow recipient={recipient} serialNumber={1} messageTypes={messageTypes} selected={false} selectionDisabled={false} onSelect={vi.fn()} editing={false} editedPhone="" onPhoneChange={vi.fn()} onEdit={vi.fn()} onCancelEdit={vi.fn()} onSavePhone={vi.fn()} phoneSaving={false} resendPending={false} onResend={onResend} removeDisabled={false} onRemove={vi.fn()} /></tbody></table>);
  return onResend;
}

it("disables original welcome resend after phone-level delivery while allowing a passport retry", () => {
  const onResend = renderRow(true);
  const welcome = screen.getByRole("button", { name: "Resend Welcome message to Alex", hidden: true });
  expect(welcome).toBeDisabled();
  fireEvent.click(welcome);
  expect(onResend).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Retry Passport link to Alex", hidden: true })).toBeEnabled();
});

it("allows failed welcome retry and blocks later messages until welcome arrives", () => {
  const onResend = renderRow(false);
  expect(screen.getByRole("button", { name: "Retry Welcome message to Alex", hidden: true })).toBeEnabled();
  const passport = screen.getByRole("button", { name: "Retry Passport link to Alex", hidden: true });
  expect(passport).toBeDisabled();
  expect(passport).toHaveAttribute("title", "Welcome must arrive before passport links.");
  fireEvent.click(passport);
  expect(onResend).not.toHaveBeenCalled();
});

it("offers group invite retry without welcome delivery and omits its welcome warning", () => {
  const onResend = renderRow(false, ["group_invite"]);
  const invitation = screen.getByRole("button", { name: "Retry Group invite to Alex", hidden: true });
  expect(invitation).toBeEnabled();
  expect(invitation).not.toHaveAttribute("title");
  expect(screen.queryByText("Welcome must arrive before passport links.")).not.toBeInTheDocument();
  fireEvent.click(invitation);
  expect(onResend).toHaveBeenCalledWith(expect.objectContaining({ messageType: "group_invite", action: "retry" }));
});
