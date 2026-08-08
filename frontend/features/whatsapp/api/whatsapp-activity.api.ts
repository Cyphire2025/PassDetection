import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export type WhatsAppActivityKind = "broadcast" | "document" | "qr";

export interface WhatsAppActivitySummary {
  activity_id: string;
  kind: WhatsAppActivityKind;
  title: string;
  context_label: string;
  source_group_id: string;
  document_type: string | null;
  total: number;
  queued: number;
  sent: number;
  failed: number;
  delivery_unknown: number;
  started_at: string;
  updated_at: string;
}

export interface WhatsAppActivityFailure {
  recipient_name: string;
  phone_number: string;
  error_message: string | null;
}

export const whatsappActivityApi = {
  summary: async (
    kind: WhatsAppActivityKind,
    batchId: string,
  ): Promise<WhatsAppActivitySummary> => {
    const { data } = await apiClient.get<WhatsAppActivitySummary>(
      API_ENDPOINTS.whatsapp.activity(kind, batchId),
    );
    return data;
  },

  failures: async (
    kind: WhatsAppActivityKind,
    batchId: string,
  ): Promise<WhatsAppActivityFailure[]> => {
    const { data } = await apiClient.get<WhatsAppActivityFailure[]>(
      API_ENDPOINTS.whatsapp.activityFailures(kind, batchId),
    );
    return data;
  },
};
