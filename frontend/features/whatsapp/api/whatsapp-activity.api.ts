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
  status_counts?: Record<string, number>;
  started_at: string;
  updated_at: string;
}

export interface WhatsAppActivityFailure {
  recipient_name: string;
  phone_number: string;
  error_message: string | null;
}

export type DocumentDeliveryActivityFilter =
  | "all"
  | "queued"
  | "processing"
  | "sent"
  | "delivered"
  | "read"
  | "failed"
  | "needs_review";

export interface DocumentDeliveryActivityItem {
  delivery_id: string;
  passenger_name: string;
  phone_number: string;
  document_filename: string;
  document_type: string;
  status: string;
  error_message: string | null;
  status_updated_at: string;
}

export interface DocumentDeliveryActivityPage {
  items: DocumentDeliveryActivityItem[];
  total: number;
  offset: number;
  limit: number;
}

export const whatsappActivityApi = {
  summary: async (
    kind: WhatsAppActivityKind,
    batchId: string,
    signal?: AbortSignal,
  ): Promise<WhatsAppActivitySummary> => {
    const { data } = await apiClient.get<WhatsAppActivitySummary>(
      API_ENDPOINTS.whatsapp.activity(kind, batchId),
      { signal },
    );
    return data;
  },

  failures: async (
    kind: WhatsAppActivityKind,
    batchId: string,
    signal?: AbortSignal,
  ): Promise<WhatsAppActivityFailure[]> => {
    const { data } = await apiClient.get<WhatsAppActivityFailure[]>(
      API_ENDPOINTS.whatsapp.activityFailures(kind, batchId),
      { signal },
    );
    return data;
  },

  documentDeliveries: async (
    batchId: string,
    params: {
      status_filter?: DocumentDeliveryActivityFilter;
      q?: string;
      offset?: number;
      limit?: number;
    },
    signal?: AbortSignal,
  ): Promise<DocumentDeliveryActivityPage> => {
    const { data } = await apiClient.get<DocumentDeliveryActivityPage>(
      API_ENDPOINTS.whatsapp.documentActivityDeliveries(batchId),
      { params, signal },
    );
    return data;
  },
};
