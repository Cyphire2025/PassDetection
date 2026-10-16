import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { WhatsAppSendResponse } from "../api/whatsapp.api";

export type HistoryFilter =
  "all" | "sent" | "not_sent" | "delivery_left" | "failed";
export type HistoryCounts = Record<HistoryFilter, number>;
export interface HistoryEntry {
  id: string;
  message_type: string;
  message_preview: string;
  rendered_message?: string | null;
  created_at: string;
  updated_at: string;
  counts: HistoryCounts;
}
export interface HistoryRecipient {
  message_log_id: string;
  recipient_id: string;
  name: string | null;
  phone_number: string;
  current_phone_number: string;
  status: string;
  error_message: string | null;
  rendered_message: string | null;
  updated_at: string;
  removed: boolean;
  can_resend: boolean;
}
export interface PageResult<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export const historyApi = {
  entry: async (groupId: string, messageId: string, signal?: AbortSignal) => {
    const { data } = await apiClient.get<HistoryEntry>(
      `${API_ENDPOINTS.whatsapp.group(groupId)}/messages/${encodeURIComponent(messageId)}`,
      { signal },
    );
    return data;
  },
  list: async (
    groupId: string,
    params: {
      q?: string;
      message_type?: string;
      offset?: number;
      limit?: number;
    },
    signal?: AbortSignal,
  ) => {
    const { data } = await apiClient.get<PageResult<HistoryEntry>>(
      `${API_ENDPOINTS.whatsapp.group(groupId)}/messages`,
      { params, signal },
    );
    return data;
  },
  recipients: async (
    groupId: string,
    messageId: string,
    params: {
      status_filter: HistoryFilter;
      q: string;
      offset: number;
      limit: number;
    },
    signal?: AbortSignal,
  ) => {
    const { data } = await apiClient.get<
      PageResult<HistoryRecipient> & { counts: HistoryCounts }
    >(
      `${API_ENDPOINTS.whatsapp.group(groupId)}/messages/${encodeURIComponent(messageId)}/recipients`,
      { params, signal },
    );
    return data;
  },
  resend: async (
    groupId: string,
    messageType: string,
    recipient: HistoryRecipient,
    requestId: string,
  ) => {
    const { data } = await apiClient.post<WhatsAppSendResponse>(
      messageType === "document_update"
        ? `${API_ENDPOINTS.whatsapp.group(groupId)}/recipients/${encodeURIComponent(recipient.recipient_id)}/resend-update`
        : API_ENDPOINTS.whatsapp.resendRecipientMessage(
            groupId,
            recipient.recipient_id,
          ),
      {
        ...(messageType === "document_update"
          ? {}
          : { message_type: messageType }),
        source_message_log_id: recipient.message_log_id,
        request_id: requestId,
      },
    );
    return data;
  },
};
