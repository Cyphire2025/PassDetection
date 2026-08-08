import type {
  WhatsAppMessageType,
} from "../api/whatsapp.api";

export type RecipientResendTarget = {
  recipientId: string;
  recipientName: string;
  phoneNumber: string;
  messageType: WhatsAppMessageType;
  action: "resend" | "retry";
};
