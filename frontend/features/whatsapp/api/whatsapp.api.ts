import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  RecipientImportPreview,
  RecipientImportRejectionReasonCode,
} from "../utils/recipient-import";

export interface WhatsAppRecipientInput {
  name?: string | null;
  phone_number: string;
  imported_fields?: Record<string, string>;
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
  imported_fields: Record<string, string>;
  message_statuses: WhatsAppRecipientMessageStatus[];
}

export interface WhatsAppRejectedContactInput {
  source_file_name: string;
  sheet_name: string;
  row_number: number;
  raw_name: string | null;
  raw_phone_number: string | null;
  reason_code: RecipientImportRejectionReasonCode;
  imported_fields?: Record<string, string>;
}

export interface WhatsAppRejectedContact extends WhatsAppRejectedContactInput {
  id: string;
  reason: string;
  created_at: string;
}

export interface WhatsAppRejectedContactPage {
  items: WhatsAppRejectedContact[];
  total: number;
  limit: number;
  offset: number;
}

export type WhatsAppRecipientRosterItem =
  | {
      kind: "recipient";
      display_order: number;
      recipient: WhatsAppRecipient;
    }
  | {
      kind: "rejected";
      display_order: number;
      rejected_contact: WhatsAppRejectedContact;
    };

export interface WhatsAppRecipientRosterResponse {
  items: WhatsAppRecipientRosterItem[];
  counts: {
    all: number;
    sent: number;
    failed: number;
    rejected: number;
  };
}

export type WhatsAppContactPreviewResponse = RecipientImportPreview;

export interface WhatsAppRecipientMessageStatus {
  message_type: string;
  status: string;
  already_sent: boolean;
  latest_resend_status: string | null;
  resend_blocked: boolean;
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
  recipient_count: number;
  recipient_opt_in_confirmed: boolean;
  created_at: string;
  updated_at: string;
}

export interface WhatsAppBroadcastGroupDetail extends WhatsAppBroadcastGroup {
  recipients: WhatsAppRecipient[];
  support_contacts: WhatsAppSupportContact[];
  rejected_contact_count: number;
}

export type WhatsAppMessageType = "welcome" | "passport_link";

export interface WhatsAppMessageDraft {
  message_type: WhatsAppMessageType;
  passport_intro?: string | null;
  passport_link?: string | null;
  message_content?: string | null;
  recipient_id?: string | null;
  resend_recipient_id?: string | null;
  header_image_id?: string | null;
  recipient_ids?: string[] | null;
  support_contact_ids?: string[] | null;
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
  passport_intro: string | null;
  passport_link: string | null;
  message_content: string;
  header_image_id: string | null;
  content_source: "default" | "latest_group" | "latest_recipient";
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

export interface WhatsAppWelcomeMediaResponse {
  media_id: string;
  file_name: string;
  content_type: string;
}

async function uploadWelcomeImage(
  groupId: string,
  image: File,
): Promise<WhatsAppWelcomeMediaResponse> {
  const formData = new FormData();
  formData.append("image", image);
  const { data } = await apiClient.post<WhatsAppWelcomeMediaResponse>(
    API_ENDPOINTS.whatsapp.welcomeMedia(groupId),
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}

export const whatsappApi = {
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

  groups: async (): Promise<WhatsAppBroadcastGroup[]> => {
    const { data } = await apiClient.get<WhatsAppBroadcastGroup[]>(API_ENDPOINTS.whatsapp.groups);
    return data;
  },

  group: async (groupId: string): Promise<WhatsAppBroadcastGroupDetail> => {
    const { data } = await apiClient.get<WhatsAppBroadcastGroupDetail>(API_ENDPOINTS.whatsapp.group(groupId));
    return data;
  },

  recipientRoster: async (
    groupId: string,
  ): Promise<WhatsAppRecipientRosterResponse> => {
    const { data } = await apiClient.get<WhatsAppRecipientRosterResponse>(
      API_ENDPOINTS.whatsapp.recipientRoster(groupId),
    );
    return data;
  },

  createGroup: async ({
    name,
    contacts,
    rejectedContacts,
    supportContacts,
    recipientOptInConfirmed,
    file,
  }: {
    name: string;
    contacts: WhatsAppRecipientInput[];
    rejectedContacts: WhatsAppRejectedContactInput[];
    supportContacts: WhatsAppSupportContactInput[];
    recipientOptInConfirmed: boolean;
    file?: File | null;
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
    if (file) formData.append("contacts_file", file);
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

  addRecipients: async ({
    groupId,
    contacts,
    rejectedContacts,
    recipientOptInConfirmed,
    file,
  }: {
    groupId: string;
    contacts: WhatsAppRecipientInput[];
    rejectedContacts: WhatsAppRejectedContactInput[];
    recipientOptInConfirmed: boolean;
    file?: File | null;
  }): Promise<WhatsAppBroadcastGroupDetail> => {
    const formData = new FormData();
    formData.append("contacts_json", JSON.stringify(contacts));
    formData.append(
      "rejected_contacts_json",
      JSON.stringify(rejectedContacts),
    );
    formData.append("recipient_opt_in_confirmed", String(recipientOptInConfirmed));
    if (file) formData.append("contacts_file", file);
    const { data } = await apiClient.post<WhatsAppBroadcastGroupDetail>(
      API_ENDPOINTS.whatsapp.recipients(groupId),
      formData,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
    return data;
  },

  rejectedContacts: async ({
    groupId,
    limit,
    offset,
  }: {
    groupId: string;
    limit: number;
    offset: number;
  }): Promise<WhatsAppRejectedContactPage> => {
    const { data } = await apiClient.get<WhatsAppRejectedContactPage>(
      API_ENDPOINTS.whatsapp.rejectedContacts(groupId),
      { params: { limit, offset } },
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

  resendRecipientMessage: async ({
    groupId,
    recipientId,
    messageType,
    passportIntro,
    passportLink,
    messageContent,
    image,
    headerImageId,
    supportContactIds,
  }: {
    groupId: string;
    recipientId: string;
    messageType: WhatsAppMessageType;
    passportIntro: string;
    passportLink: string;
    messageContent: string;
    image: File | null;
    headerImageId: string | null;
    supportContactIds?: string[] | null;
  }): Promise<WhatsAppSendResponse> => {
    const resolvedHeaderImageId = image
      ? (await uploadWelcomeImage(groupId, image)).media_id
      : headerImageId;
    const { data } = await apiClient.post<WhatsAppSendResponse>(
      API_ENDPOINTS.whatsapp.resendRecipientMessage(groupId, recipientId),
      {
        message_type: messageType,
        passport_intro:
          messageType === "passport_link" ? passportIntro : null,
        passport_link:
          messageType === "passport_link" ? passportLink : null,
        message_content: messageContent,
        header_image_id: resolvedHeaderImageId,
        support_contact_ids:
          messageType === "passport_link" ? supportContactIds ?? null : null,
      },
    );
    return data;
  },

  previewMessage: async (
    groupId: string,
    draft: WhatsAppMessageDraft,
    signal?: AbortSignal,
  ): Promise<WhatsAppPreviewResponse> => {
    const { data } = await apiClient.post<WhatsAppPreviewResponse>(
      API_ENDPOINTS.whatsapp.preview(groupId),
      draft,
      { signal },
    );
    return data;
  },

  uploadWelcomeImage,

  sendWelcome: async (
    groupId: string,
    messageContent: string,
    image: File | null,
    headerImageId: string | null,
    recipientIds: string[] | null = null,
  ): Promise<WhatsAppSendResponse> => {
    const resolvedHeaderImageId = image
      ? (await uploadWelcomeImage(groupId, image)).media_id
      : headerImageId;
    const { data } = await apiClient.post<WhatsAppSendResponse>(API_ENDPOINTS.whatsapp.send(groupId), {
      message_type: "welcome",
      message_content: messageContent,
      header_image_id: resolvedHeaderImageId,
      recipient_ids: recipientIds,
    });
    return data;
  },

  sendPassportLink: async (
    groupId: string,
    passportIntro: string,
    passportLink: string,
    messageContent: string,
    image: File | null,
    headerImageId: string | null,
    recipientIds: string[] | null = null,
    supportContactIds: string[] | null = null,
  ): Promise<WhatsAppSendResponse> => {
    const resolvedHeaderImageId = image
      ? (await uploadWelcomeImage(groupId, image)).media_id
      : headerImageId;
    const { data } = await apiClient.post<WhatsAppSendResponse>(API_ENDPOINTS.whatsapp.send(groupId), {
      message_type: "passport_link",
      passport_intro: passportIntro,
      passport_link: passportLink,
      message_content: messageContent,
      header_image_id: resolvedHeaderImageId,
      recipient_ids: recipientIds,
      support_contact_ids: supportContactIds,
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
