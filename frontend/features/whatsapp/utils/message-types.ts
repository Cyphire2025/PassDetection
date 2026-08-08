import type { WhatsAppMessageType } from "../api/whatsapp.api";

export function formatMessageType(messageType: string): string {
  if (messageType === "welcome") return "Welcome message";
  if (messageType === "passport_link") return "Passport link";
  if (messageType === "reminder") return "Reminder";
  return messageType
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function isWhatsAppMessageType(
  messageType: string,
): messageType is WhatsAppMessageType {
  return (
    messageType === "welcome" ||
    messageType === "passport_link" ||
    messageType === "reminder"
  );
}
