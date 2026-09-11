import { describe, expect, it } from "vitest";
import { canRetryOrResendRecipient, isRecipientEligible, type RecipientDeliveryState, welcomeDeliveryBlockReason } from "./recipient-delivery";
import { getBulkResendEligibility } from "./recipient-bulk-selection";

const state = (type: string, status: string, alreadySent = false) => ({ message_type: type, status, already_sent: alreadySent, latest_resend_status: null, resend_blocked: false, submitted_at: null, status_updated_at: "2026-09-12T00:00:00Z" });

describe("agency and phone welcome gates in the original WhatsApp workspace", () => {
  it.each(["queued", "processing", "submitted", "sent", "delivered", "read", "delivery_unknown"])("blocks duplicate welcome for %s even when this list has no local welcome", (welcomeStatus) => {
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
    expect(getBulkResendEligibility(failed, "welcome")).toBe("eligible");
  });

  it("blocks original bulk passport resend until the destination welcome is delivered", () => {
    const recipient = { welcome_delivered: false, welcome_status: "required", message_statuses: [state("passport_link", "sent", true)] };
    expect(getBulkResendEligibility(recipient, "passport_link")).toBe("blocked");
    expect(getBulkResendEligibility({ ...recipient, welcome_delivered: true, welcome_status: "read" }, "passport_link")).toBe("eligible");
  });
});
