import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { downloadStreamedResponse } from "@/lib/api/streamed-download";
import type { WhatsAppMessageType, WhatsAppRecipientRosterItem } from "./whatsapp.api";

export type WhatsAppExportItem =
  | { kind: "recipient" | "rejected" | "replaced" | "unidentified"; id: string }
  | { kind: "source_contact"; id: string; source_group_id: string };

export interface WhatsAppExportRequest {
  view: "delivery" | "travellers";
  items: WhatsAppExportItem[];
  filter_label: string;
  message_type?: WhatsAppMessageType;
}

export function rosterItemForExport(item: WhatsAppRecipientRosterItem): WhatsAppExportItem {
  if (item.kind === "recipient") return { kind: item.kind, id: item.recipient.id };
  if (item.kind === "rejected") return { kind: item.kind, id: item.rejected_contact.id };
  if (item.kind === "replaced") return { kind: item.kind, id: item.replaced_recipient.recipient_id };
  return { kind: item.kind, id: item.unidentified_upload.submission_id };
}

export async function exportWhatsAppExcel(
  groupId: string,
  groupName: string,
  request: WhatsAppExportRequest,
  signal: AbortSignal,
) {
  const messagePrefix = request.message_type ? `${request.message_type}-` : "";
  return downloadStreamedResponse({
    url: API_ENDPOINTS.whatsapp.groupExport(groupId),
    method: "POST",
    data: request,
    suggestedFilename: `${groupName}-${messagePrefix}${request.filter_label}-${request.view}.xlsx`,
    signal,
    validateHeaders: (headers) => {
      const contentType = String(headers["content-type"] ?? "").split(";")[0].trim().toLowerCase();
      if (contentType !== "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") {
        throw new Error("The export did not return an Excel workbook. Please try again.");
      }
    },
  });
}
