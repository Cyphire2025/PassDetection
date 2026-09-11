import type { TravellerWelcomeRecipient } from "@/types/document-distribution.types";

export const MAX_WELCOME_NUMBERS_PER_SEND = 1_500;

export function selectedWelcomePhones(eligiblePhones: string[], selection: string[] | null) {
  const eligibleSet = new Set(eligiblePhones);
  return Array.from(new Set(selection ?? eligiblePhones))
    .filter((phone) => eligibleSet.has(phone))
    .slice(0, MAX_WELCOME_NUMBERS_PER_SEND);
}

export function eligibleWelcomePhones(recipients: TravellerWelcomeRecipient[]) {
  return Array.from(new Set(recipients.flatMap((row) => (
    row.eligible && row.phone_number && row.rendered_message ? [row.phone_number] : []
  ))));
}

export function welcomeStatusLabel(status: string) {
  if (status === "delivered" || status === "read") return "Welcome delivered";
  if (status === "submitted" || status === "sent") return "Awaiting delivery";
  if (status === "queued" || status === "processing") return "Welcome in progress";
  if (status === "failed") return "Welcome failed";
  if (status === "delivery_unknown") return "Delivery unconfirmed";
  if (status === "required") return "Welcome needed";
  return "Blocked";
}

export function welcomeStatusTone(status: string): "success" | "warning" | "outline" {
  if (status === "delivered" || status === "read") return "success";
  if (["required", "failed", "delivery_unknown"].includes(status)) return "warning";
  return "outline";
}
