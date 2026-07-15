import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export interface WhatsAppRecipientInput {
  name?: string | null;
  phone_number: string;
}

export interface WhatsAppRecipient {
  id: string;
  name: string | null;
  phone_number: string;
  normalized_phone_number: string;
}

export interface WhatsAppBroadcastGroup {
  id: string;
  name: string;
  recipient_count: number;
  created_at: string;
  updated_at: string;
}

export interface WhatsAppBroadcastGroupDetail extends WhatsAppBroadcastGroup {
  recipients: WhatsAppRecipient[];
}

export interface WhatsAppSendResponse {
  sent: number;
  failed: number;
  results: Array<{
    recipient_id: string;
    phone_number: string;
    status: string;
    provider_message_id?: string | null;
    error_message?: string | null;
  }>;
}

export const whatsappApi = {
  groups: async (): Promise<WhatsAppBroadcastGroup[]> => {
    const { data } = await apiClient.get<WhatsAppBroadcastGroup[]>(API_ENDPOINTS.whatsapp.groups);
    return data;
  },

  group: async (groupId: string): Promise<WhatsAppBroadcastGroupDetail> => {
    const { data } = await apiClient.get<WhatsAppBroadcastGroupDetail>(API_ENDPOINTS.whatsapp.group(groupId));
    return data;
  },

  createGroup: async ({
    name,
    contacts,
    file,
  }: {
    name: string;
    contacts: WhatsAppRecipientInput[];
    file?: File | null;
  }): Promise<WhatsAppBroadcastGroupDetail> => {
    const formData = new FormData();
    formData.append("name", name);
    formData.append("contacts_json", JSON.stringify(contacts));
    if (file) formData.append("contacts_file", file);
    const { data } = await apiClient.post<WhatsAppBroadcastGroupDetail>(API_ENDPOINTS.whatsapp.groups, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data;
  },

  deleteGroup: async (groupId: string): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.whatsapp.group(groupId));
  },

  sendWelcome: async (groupId: string): Promise<WhatsAppSendResponse> => {
    const { data } = await apiClient.post<WhatsAppSendResponse>(API_ENDPOINTS.whatsapp.send(groupId), {
      message_type: "welcome",
    });
    return data;
  },

  sendPassportLink: async (groupId: string, passportLink: string): Promise<WhatsAppSendResponse> => {
    const { data } = await apiClient.post<WhatsAppSendResponse>(API_ENDPOINTS.whatsapp.send(groupId), {
      message_type: "passport_link",
      passport_link: passportLink,
    });
    return data;
  },
};
