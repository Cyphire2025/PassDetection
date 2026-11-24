import apiClient from '@/lib/api/client';
import { API_ENDPOINTS } from '@/lib/api/endpoints';
import type { WhatsAppRecipientInput, WhatsAppRecipientDetailsEdit, WhatsAppRejectedContactInput, WhatsAppRecipientRosterResponse } from '../types/recipients';
import type { WhatsAppBroadcastGroupDetail } from '../types/groups';

export const whatsappRecipientsApi = {
  recipientRoster: async (
    groupId: string,
    signal?: AbortSignal,
  ): Promise<WhatsAppRecipientRosterResponse> => {
    const { data } = await apiClient.get<WhatsAppRecipientRosterResponse>(
      API_ENDPOINTS.whatsapp.recipientRoster(groupId),
      { signal },
    );
    return data;
  },
  restoreReplacedRecipient: async ({
    clientGroupId,
    resolutionId,
  }: {
    clientGroupId: string;
    resolutionId: string;
  }): Promise<void> => {
    await apiClient.post(
      API_ENDPOINTS.uploadLinks.restoreRosterResolution(
        clientGroupId,
        resolutionId,
      ),
    );
  },
  addRecipients: async ({
    groupId,
    contacts,
    rejectedContacts,
    recipientOptInConfirmed,
    importedFieldKeys,
    file,
    duplicateSourceFiles,
  }: {
    groupId: string;
    contacts: WhatsAppRecipientInput[];
    rejectedContacts: WhatsAppRejectedContactInput[];
    recipientOptInConfirmed: boolean;
    importedFieldKeys?: string[];
    file?: File | null;
    duplicateSourceFiles?: File[];
  }): Promise<WhatsAppBroadcastGroupDetail> => {
    const formData = new FormData();
    formData.append("contacts_json", JSON.stringify(contacts));
    formData.append(
      "rejected_contacts_json",
      JSON.stringify(rejectedContacts),
    );
    formData.append("recipient_opt_in_confirmed", String(recipientOptInConfirmed));
    formData.append("imported_field_keys_json", JSON.stringify(importedFieldKeys ?? []));
    if (file) formData.append("contacts_file", file);
    for (const sourceFile of duplicateSourceFiles ?? []) formData.append("duplicate_source_files", sourceFile);
    const { data } = await apiClient.post<WhatsAppBroadcastGroupDetail>(
      API_ENDPOINTS.whatsapp.recipients(groupId),
      formData,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
    return data;
  },
  resolveRejectedContact: async ({
    groupId,
    rejectedContactId,
    name,
    phoneNumber,
    recipientOptInConfirmed,
  }: {
    groupId: string;
    rejectedContactId: string;
    name: string;
    phoneNumber: string;
    recipientOptInConfirmed: boolean;
  }): Promise<WhatsAppBroadcastGroupDetail> => {
    const { data } = await apiClient.post<WhatsAppBroadcastGroupDetail>(
      API_ENDPOINTS.whatsapp.resolveRejectedContact(
        groupId,
        rejectedContactId,
      ),
      {
        name,
        phone_number: phoneNumber,
        recipient_opt_in_confirmed: recipientOptInConfirmed,
      },
    );
    return data;
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
  updateRecipientPhone: async ({
    groupId,
    recipientId,
    phoneNumber,
  }: {
    groupId: string;
    recipientId: string;
    phoneNumber: string;
  }): Promise<WhatsAppBroadcastGroupDetail> => {
    const { data } = await apiClient.patch<WhatsAppBroadcastGroupDetail>(
      API_ENDPOINTS.whatsapp.recipient(groupId, recipientId),
      { phone_number: phoneNumber },
    );
    return data;
  },
  updateRecipientDetails: async ({ groupId, recipientId, details }: {
    groupId: string;
    recipientId: string;
    details: WhatsAppRecipientDetailsEdit;
  }): Promise<WhatsAppBroadcastGroupDetail> => {
    const { data } = await apiClient.patch<WhatsAppBroadcastGroupDetail>(
      API_ENDPOINTS.whatsapp.recipientDetails(groupId, recipientId), details,
    );
    return data;
  }
};
