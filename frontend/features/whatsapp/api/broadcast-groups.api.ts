import apiClient from '@/lib/api/client';
import { API_ENDPOINTS } from '@/lib/api/endpoints';
import type { WhatsAppRecipientInput, WhatsAppSupportContactInput, WhatsAppRejectedContactInput, WhatsAppContactPreviewResponse } from '../types/recipients';
import type { WhatsAppBroadcastGroup, WhatsAppBroadcastGroupDetail } from '../types/groups';

export const whatsappGroupsApi = {
  previewContacts: async (
    file: File,
    signal?: AbortSignal,
  ): Promise<WhatsAppContactPreviewResponse> => {
    const formData = new FormData();
    formData.append("contacts_file", file);
    const { data } = await apiClient.post<WhatsAppContactPreviewResponse>(
      API_ENDPOINTS.whatsapp.contactsPreview,
      formData,
      {
        headers: { "Content-Type": "multipart/form-data" },
        signal,
      },
    );
    return data;
  },
  groups: async (archived = false, signal?: AbortSignal): Promise<WhatsAppBroadcastGroup[]> => {
    const { data } = await apiClient.get<WhatsAppBroadcastGroup[]>(API_ENDPOINTS.whatsapp.groups, {
      params: { archived },
      signal,
    });
    return data;
  },
  archiveGroup: async (groupId: string): Promise<WhatsAppBroadcastGroupDetail> => {
    const { data } = await apiClient.post<WhatsAppBroadcastGroupDetail>(
      `${API_ENDPOINTS.whatsapp.group(groupId)}/archive`,
    );
    return data;
  },
  restoreGroup: async (groupId: string): Promise<WhatsAppBroadcastGroupDetail> => {
    const { data } = await apiClient.post<WhatsAppBroadcastGroupDetail>(
      `${API_ENDPOINTS.whatsapp.group(groupId)}/restore`,
    );
    return data;
  },
  group: async (groupId: string, signal?: AbortSignal): Promise<WhatsAppBroadcastGroupDetail> => {
    const { data } = await apiClient.get<WhatsAppBroadcastGroupDetail>(API_ENDPOINTS.whatsapp.group(groupId), { signal });
    return data;
  },
  createGroup: async ({
    name,
    contacts,
    rejectedContacts,
    supportContacts,
    recipientOptInConfirmed,
    importedFieldKeys,
    file,
    duplicateSourceFiles,
  }: {
    name: string;
    contacts: WhatsAppRecipientInput[];
    rejectedContacts: WhatsAppRejectedContactInput[];
    supportContacts: WhatsAppSupportContactInput[];
    recipientOptInConfirmed: boolean;
    importedFieldKeys?: string[];
    file?: File | null;
    duplicateSourceFiles?: File[];
  }): Promise<WhatsAppBroadcastGroupDetail> => {
    const formData = new FormData();
    formData.append("name", name);
    formData.append("contacts_json", JSON.stringify(contacts));
    formData.append(
      "rejected_contacts_json",
      JSON.stringify(rejectedContacts),
    );
    formData.append("support_contacts_json", JSON.stringify(supportContacts));
    formData.append("recipient_opt_in_confirmed", String(recipientOptInConfirmed));
    formData.append("imported_field_keys_json", JSON.stringify(importedFieldKeys ?? []));
    if (file) formData.append("contacts_file", file);
    for (const sourceFile of duplicateSourceFiles ?? []) formData.append("duplicate_source_files", sourceFile);
    const { data } = await apiClient.post<WhatsAppBroadcastGroupDetail>(API_ENDPOINTS.whatsapp.groups, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data;
  },
  updateGroup: async ({
    groupId,
    name,
    supportContacts,
  }: {
    groupId: string;
    name?: string;
    supportContacts?: WhatsAppSupportContactInput[];
  }): Promise<WhatsAppBroadcastGroupDetail> => {
    const formData = new FormData();
    if (name !== undefined) formData.append("name", name);
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
  deleteGroup: async (groupId: string): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.whatsapp.group(groupId));
  }
};
