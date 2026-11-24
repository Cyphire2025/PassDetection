import type { WhatsAppRejectedContactInput } from "../api/whatsapp.api";
import type { RecipientImportRejectedRowWithSource } from "./recipient-import";

export type RejectedContactDraft = RecipientImportRejectedRowWithSource;

export function toRejectedContactInputs(
  contacts: RejectedContactDraft[],
): WhatsAppRejectedContactInput[] {
  return contacts.map((contact) => ({
    source_file_name: contact.source_file_name,
    sheet_name: contact.sheet_name,
    row_number: contact.row_number,
    raw_name: contact.raw_name,
    raw_phone_number: contact.raw_phone_number,
    reason_code: contact.reason_code,
    imported_fields: contact.imported_fields,
  }));
}

export type RecipientImportState =
  | { status: "idle" }
  | { status: "loading"; fileName: string }
  | {
      status: "success";
      fileName: string;
      acceptedCount: number;
      addedCount: number;
      duplicateCount: number;
      rejectedCount: number;
      rejectedRows: RejectedContactDraft[];
      rejectedRowsTruncated: boolean;
      omittedRejectedCount: number;
      matchingFieldCount: number;
      retainedSourceFileCount: number;
    }
  | { status: "error"; fileName: string; message: string };

