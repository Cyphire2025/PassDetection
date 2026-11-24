import type { MessageField } from "./composer.api";

export interface ComposerState {
  fields: Partial<Record<MessageField["key"], string>>;
  recipientIds: string[] | null;
  previewRecipientId: string | null;
  reminderAudience: "all" | "not_submitted";
  reminderGroupId: string | null;
  submission: "all" | "submitted" | "not_submitted";
  distribution: "all" | "sent" | "pending";
  documentType: string;
  supportContactId: string | null;
  includePreviousRecipients: boolean;
}
