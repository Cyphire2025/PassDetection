import { describe, expect, it } from "vitest";
import { canRetryOrResendRecipient, countEligibleRecipients, isRecipientEligible, type RecipientDeliveryState, welcomeDeliveryBlockReason } from "./recipient-delivery";
import type { WhatsAppRecipient } from "../api/whatsapp.api";

const state = (type: string, status: string, alreadySent = false) => ({ message_type: type, status, already_sent: alreadySent, latest_resend_status: null, resend_blocked: false, submitted_at: null, status_updated_at: "2026-09-12T00:00:00Z" });

const welcomeAwaitingReceipt: WhatsAppRecipient = {
  id: "synthetic-vishamber",
  name: "Vishamber (synthetic)",
  phone_number: "+12025550123",
  normalized_phone_number: "+12025550123",
  imported_fields: {},
  welcome_status: "sent",
  welcome_delivered: false,
  message_statuses: [{ ...state("welcome", "sent", true), latest_resend_status: "sent" }],
};

describe("shared recipient delivery welcome gates", () => {
  it("does not inherit another broadcast's welcome delivery", () => {
    const recipient = { id: "current-contact", name: "Alex", phone_number: "+919900000001", normalized_phone_number: "+919900000001", imported_fields: {}, welcome_status: null, welcome_delivered: false, message_statuses: [] };
    expect(isRecipientEligible(recipient, "welcome")).toBe(true);
    expect(welcomeDeliveryBlockReason(recipient, "welcome")).toBeNull();
    expect(isRecipientEligible(recipient, "passport_link")).toBe(false);
  });

  it("keeps later message gates closed until an accepted welcome resend is delivered", () => {
    const recipient = welcomeAwaitingReceipt;

    expect(isRecipientEligible(recipient, "welcome")).toBe(false);
    for (const messageType of ["passport_link", "reminder"]) {
      expect(isRecipientEligible(recipient, messageType)).toBe(false);
      expect(countEligibleRecipients([recipient], messageType)).toBe(0);
      expect(welcomeDeliveryBlockReason(recipient, messageType)).toMatch(/Welcome must be delivered/);
    }
  });

  it.each(["delivered", "read"])("opens later message gates when welcome is %s", (welcomeStatus) => {
    const recipient: WhatsAppRecipient = {
      ...welcomeAwaitingReceipt,
      welcome_status: welcomeStatus,
      welcome_delivered: true,
      message_statuses: [{ ...state("welcome", welcomeStatus, true), latest_resend_status: welcomeStatus }],
    };

    expect(isRecipientEligible(recipient, "welcome")).toBe(false);
    for (const messageType of ["passport_link", "reminder"]) {
      expect(isRecipientEligible(recipient, messageType)).toBe(true);
      expect(countEligibleRecipients([recipient], messageType)).toBe(1);
      expect(welcomeDeliveryBlockReason(recipient, messageType)).toBeNull();
    }
  });

  it.each(["queued", "processing", "submitted", "sent", "delivered", "read", "delivery_unknown"])("blocks duplicate welcome for %s from a direct send in the same broadcast", (welcomeStatus) => {
    const recipient: RecipientDeliveryState = { welcome_status: welcomeStatus, welcome_delivered: ["delivered", "read"].includes(welcomeStatus), message_statuses: [] };
    expect(isRecipientEligible(recipient, "welcome")).toBe(false);
    expect(welcomeDeliveryBlockReason(recipient, "welcome")).toMatch(/Another welcome cannot be sent/);
    expect(canRetryOrResendRecipient({ ...recipient, message_statuses: [state("welcome", "failed")] }, "welcome", "retry")).toBe(false);
  });

  it.each(["passport_link", "reminder"])("blocks %s when welcome delivery is explicitly absent", (messageType) => {
    const recipient: RecipientDeliveryState = { welcome_status: "sent", welcome_delivered: false, welcome_required_reason: "Wait for welcome delivery confirmation.", message_statuses: [state(messageType, "failed")] };
    expect(isRecipientEligible(recipient, messageType)).toBe(false);
    expect(canRetryOrResendRecipient(recipient, messageType, "retry")).toBe(false);
    expect(welcomeDeliveryBlockReason(recipient, messageType)).toBe("Wait for welcome delivery confirmation.");
  });

  it.each(["delivered", "read"])("allows later messages after welcome is %s even without local welcome history", (welcomeStatus) => {
    const recipient: RecipientDeliveryState = { welcome_status: welcomeStatus, welcome_delivered: true, message_statuses: [] };
    expect(isRecipientEligible(recipient, "passport_link")).toBe(true);
    expect(isRecipientEligible(recipient, "reminder")).toBe(true);
  });

  it("supports older responses without welcome fields and keeps genuine failed welcome retries", () => {
    expect(isRecipientEligible({ message_statuses: [] }, "passport_link")).toBe(true);
    const failed = { message_statuses: [state("welcome", "failed")] };
    expect(canRetryOrResendRecipient(failed, "welcome", "retry")).toBe(true);
  });

  it.each(["required", "failed", "queued", "processing", "sent", "delivery_unknown"])("allows group invitations when welcome is %s", (welcomeStatus) => {
    const recipient: RecipientDeliveryState = { welcome_status: welcomeStatus, welcome_delivered: false, welcome_required_reason: "Welcome must arrive first.", message_statuses: [] };
    expect(welcomeDeliveryBlockReason(recipient, "group_invite")).toBeNull();
    expect(isRecipientEligible(recipient, "group_invite")).toBe(true);
    const failed = { ...recipient, message_statuses: [state("group_invite", "failed")] };
    const delivered = { ...recipient, message_statuses: [state("group_invite", "delivered", true)] };
    expect(canRetryOrResendRecipient(failed, "group_invite", "retry")).toBe(true);
    expect(canRetryOrResendRecipient(delivered, "group_invite", "resend")).toBe(false);
  });

  it.each(["queued", "processing", "delivery_unknown"])("preserves group invite %s exclusions without a welcome", (deliveryStatus) => {
    const recipient = { welcome_delivered: false, message_statuses: [state("group_invite", deliveryStatus)] };
    expect(isRecipientEligible(recipient, "group_invite")).toBe(false);
    expect(canRetryOrResendRecipient(recipient, "group_invite", "retry")).toBe(false);
    expect(canRetryOrResendRecipient(recipient, "group_invite", "resend")).toBe(false);
    const latestResend = { ...recipient, message_statuses: [{ ...state("group_invite", "delivered", true), latest_resend_status: deliveryStatus, resend_blocked: true }] };
    expect(canRetryOrResendRecipient(latestResend, "group_invite", "resend")).toBe(false);
  });

  it("keeps already-sent, blocked, and missing-snapshot invitation exclusions", () => {
    const recipient = { welcome_delivered: false, message_statuses: [{ ...state("group_invite", "delivered", true), resend_blocked: true }] };
    expect(isRecipientEligible(recipient, "group_invite")).toBe(false);
    expect(canRetryOrResendRecipient(recipient, "group_invite", "resend")).toBe(false);
  });
});
