import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export interface WhatsAppRecipientInput {
  name?: string | null;
  phone_number: string;
}

export interface WhatsAppSupportContactInput {
  name: string;
  phone_number: string;
}

export interface WhatsAppRecipient {
  id: string;
  name: string | null;
  phone_number: string;
  normalized_phone_number: string;
  message_statuses: WhatsAppRecipientMessageStatus[];
}

export interface WhatsAppRecipientMessageStatus {
  message_type: string;
  status: string;
  already_sent: boolean;
  submitted_at: string | null;
  status_updated_at: string;
}

export interface WhatsAppSupportContact {
  id: string;
  name: string;
  phone_number: string;
  normalized_phone_number: string;
}

export interface WhatsAppBroadcastGroup {
  id: string;
  name: string;
  organizing_company_name: string;
  recipient_count: number;
  recipient_opt_in_confirmed: boolean;
  created_at: string;
  updated_at: string;
}

export interface WhatsAppBroadcastGroupDetail extends WhatsAppBroadcastGroup {
  recipients: WhatsAppRecipient[];
  support_contacts: WhatsAppSupportContact[];
}

export type WhatsAppMessageType = "welcome" | "passport_link";

export interface WhatsAppMessageDraft {
  message_type: WhatsAppMessageType;
  passport_link?: string | null;
  message_content?: string | null;
  recipient_id?: string | null;
}

export interface WhatsAppPreviewResponse {
  message_type: WhatsAppMessageType;
  template_name: string;
  recipient_id: string;
  recipient_name: string;
  recipient_count: number;
  eligible_recipient_count: number;
  already_sent_count: number;
  in_progress_count: number;
  uncertain_recipient_count: number;
  message_content: string;
  rendered_message: string;
  header_parameter_values: string[];
  parameter_values: string[];
}

export interface WhatsAppSendResponse {
  batch_id?: string | null;
  queued: number;
  sent: number;
  failed: number;
  delivery_unknown: number;
  skipped_already_sent: number;
  skipped_in_progress: number;
  skipped_delivery_unknown: number;
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
    organizingCompanyName,
    contacts,
    supportContacts,
    recipientOptInConfirmed,
    file,
  }: {
    name: string;
    organizingCompanyName: string;
    contacts: WhatsAppRecipientInput[];
    supportContacts: WhatsAppSupportContactInput[];
    recipientOptInConfirmed: boolean;
    file?: File | null;
  }): Promise<WhatsAppBroadcastGroupDetail> => {
    const formData = new FormData();
    formData.append("name", name);
    formData.append("organizing_company_name", organizingCompanyName);
    formData.append("contacts_json", JSON.stringify(contacts));
    formData.append("support_contacts_json", JSON.stringify(supportContacts));
    formData.append("recipient_opt_in_confirmed", String(recipientOptInConfirmed));
    if (file) formData.append("contacts_file", file);
    const { data } = await apiClient.post<WhatsAppBroadcastGroupDetail>(API_ENDPOINTS.whatsapp.groups, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data;
  },

  updateGroup: async ({
    groupId,
    name,
    organizingCompanyName,
    supportContacts,
  }: {
    groupId: string;
    name?: string;
    organizingCompanyName?: string;
    supportContacts?: WhatsAppSupportContactInput[];
  }): Promise<WhatsAppBroadcastGroupDetail> => {
    const formData = new FormData();
    if (name !== undefined) formData.append("name", name);
    if (organizingCompanyName !== undefined) {
      formData.append("organizing_company_name", organizingCompanyName);
    }
    if (supportContacts !== undefined) {
      formData.append("support_contacts_json", JSON.stringify(supportContacts));
    }
    const { data } = await apiClient.patch<WhatsAppBroadcastGroupDetail>(
      API_ENDPOINTS.whatsapp.group(groupId),
      formData,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
    return data;
  },

  addRecipients: async ({
    groupId,
    contacts,
    recipientOptInConfirmed,
    file,
  }: {
    groupId: string;
    contacts: WhatsAppRecipientInput[];
    recipientOptInConfirmed: boolean;
    file?: File | null;
  }): Promise<WhatsAppBroadcastGroupDetail> => {
    const formData = new FormData();
    formData.append("contacts_json", JSON.stringify(contacts));
    formData.append("recipient_opt_in_confirmed", String(recipientOptInConfirmed));
    if (file) formData.append("contacts_file", file);
    const { data } = await apiClient.post<WhatsAppBroadcastGroupDetail>(
      API_ENDPOINTS.whatsapp.recipients(groupId),
      formData,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
    return data;
  },

  deleteGroup: async (groupId: string): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.whatsapp.group(groupId));
  },

  deleteRecipient: async ({
    groupId,
    recipientId,
  }: {
    groupId: string;
    recipientId: string;
  }): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.whatsapp.recipient(groupId, recipientId));
  },

  previewMessage: async (
    groupId: string,
    draft: WhatsAppMessageDraft,
  ): Promise<WhatsAppPreviewResponse> => {
    const { data } = await apiClient.post<WhatsAppPreviewResponse>(
      API_ENDPOINTS.whatsapp.preview(groupId),
      draft,
    );
    return data;
  },

  sendWelcome: async (groupId: string, messageContent: string): Promise<WhatsAppSendResponse> => {
    const { data } = await apiClient.post<WhatsAppSendResponse>(API_ENDPOINTS.whatsapp.send(groupId), {
      message_type: "welcome",
      message_content: messageContent,
    });
    return data;
  },

  sendPassportLink: async (
    groupId: string,
    passportLink: string,
    messageContent: string,
  ): Promise<WhatsAppSendResponse> => {
    const { data } = await apiClient.post<WhatsAppSendResponse>(API_ENDPOINTS.whatsapp.send(groupId), {
      message_type: "passport_link",
      passport_link: passportLink,
      message_content: messageContent,
    });
    return data;
  },

  batchStatus: async (batchId: string): Promise<WhatsAppSendResponse> => {
    const { data } = await apiClient.get<WhatsAppSendResponse>(
      API_ENDPOINTS.whatsapp.batch(batchId),
    );
    return data;
  },
};
