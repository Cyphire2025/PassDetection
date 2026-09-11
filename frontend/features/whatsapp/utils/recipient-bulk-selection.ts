import type {
  WhatsAppBulkResendMessageType,
} from "../api/whatsapp.api";
import { type RecipientDeliveryState, welcomeDeliveryBlockReason } from "./recipient-delivery";

export type BulkResendEligibility =
  | "eligible"
  | "no_saved_message"
  | "in_progress"
  | "delivery_unknown"
  | "blocked";

/** Review estimate only; the server validates the saved snapshot before queuing. */
export function getBulkResendEligibility(
  recipient: RecipientDeliveryState,
  messageType: WhatsAppBulkResendMessageType,
): BulkResendEligibility {
  if (messageType !== "welcome" && welcomeDeliveryBlockReason(recipient, messageType)) return "blocked";
  const state = recipient.message_statuses.find((item) => item.message_type === messageType);
  if (!state) return "no_saved_message";
  const statuses = [state.status, state.latest_resend_status];
  if (statuses.includes("delivery_unknown")) return "delivery_unknown";
  if (statuses.some((value) => value === "queued" || value === "processing")) return "in_progress";
  if (state.resend_blocked) return "blocked";
  if (welcomeDeliveryBlockReason(recipient, messageType)) return "blocked";
  if (state.already_sent || statuses.includes("failed")) return "eligible";
  return "no_saved_message";
}

export function summarizeBulkResend(
  recipients: ReadonlyArray<RecipientDeliveryState>,
  messageType: WhatsAppBulkResendMessageType,
) {
  const summary = {
    selected: recipients.length,
    eligible: 0,
    noSavedMessage: 0,
    inProgress: 0,
    deliveryUnknown: 0,
    blocked: 0,
  };
  for (const recipient of recipients) {
    switch (getBulkResendEligibility(recipient, messageType)) {
      case "eligible": summary.eligible++; break;
      case "no_saved_message": summary.noSavedMessage++; break;
      case "in_progress": summary.inProgress++; break;
      case "delivery_unknown": summary.deliveryUnknown++; break;
      case "blocked": summary.blocked++; break;
    }
  }
  return summary;
}
