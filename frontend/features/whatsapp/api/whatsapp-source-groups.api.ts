import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  WhatsAppBroadcastGroupDetail,
  WhatsAppRecipientInput,
  WhatsAppSupportContactInput,
  whatsappApi,
} from "./whatsapp.api";

export interface WhatsAppSourceGroup {
  id: string;
  name: string;
  import_only?: boolean;
  submission_count: number;
}

export interface WhatsAppSourceContact {
  source_submission_id: string;
  name: string;
  phone_number: string;
  normalized_phone_number: string | null;
  issue: string | null;
  imported_fields: Record<string, string>;
}

export interface WhatsAppBroadcastSourceContacts {
  sources: { id: string; name: string; import_only: boolean }[];
  total_contacts: number;
  unique_phone_count: number;
  needs_attention_count: number;
  shared_phone_count: number;
  contacts: (WhatsAppSourceContact & {
    source_group_id: string;
    source_group_name: string;
    source_import_only: boolean;
    recipient_id: string | null;
  })[];
}

export interface WhatsAppSourceGroupPreview {
  source_group_id: string;
  source_group_name: string;
  source_import_only?: boolean;
  total_submissions: number;
  recipient_count: number;
  recipients: (WhatsAppRecipientInput & { source_submission_id?: string })[];
  contacts?: WhatsAppSourceContact[];
  shared_phone_count?: number;
  needs_attention_count?: number;
  excluded_count: number;
  excluded_counts: {
    missing_phone: number;
    invalid_phone: number;
    unverified_phone: number;
    missing_name: number;
    name_too_long: number;
    duplicate_phone: number;
  };
  preview_revision: string;
}

export interface CreateWhatsAppGroupFromSourceInput {
  sourceGroupId: string;
  name: string;
  supportContacts: WhatsAppSupportContactInput[];
  recipientOptInConfirmed: boolean;
  previewRevision: string;
}

export type CreateWhatsAppGroupInput =
  | Parameters<typeof whatsappApi.createGroup>[0]
  | CreateWhatsAppGroupFromSourceInput;

export const whatsappSourceGroupsApi = {
  list: async (signal?: AbortSignal): Promise<WhatsAppSourceGroup[]> => {
    const { data } = await apiClient.get<WhatsAppSourceGroup[]>(
      API_ENDPOINTS.whatsapp.sourceGroups,
      { signal },
    );
    return data;
  },

  preview: async (groupId: string, signal?: AbortSignal): Promise<WhatsAppSourceGroupPreview> => {
    const { data } = await apiClient.get<WhatsAppSourceGroupPreview>(
      API_ENDPOINTS.whatsapp.sourceGroupPreview(groupId),
      { signal },
    );
    return data;
  },

  groupContacts: async (groupId: string, signal?: AbortSignal): Promise<WhatsAppBroadcastSourceContacts> => {
    const { data } = await apiClient.get<WhatsAppBroadcastSourceContacts>(
      API_ENDPOINTS.whatsapp.sourceContacts(groupId),
      { signal },
    );
    return data;
  },

  create: async (input: CreateWhatsAppGroupFromSourceInput): Promise<WhatsAppBroadcastGroupDetail> => {
    const { data } = await apiClient.post<{
      group: WhatsAppBroadcastGroupDetail;
      source: WhatsAppSourceGroupPreview;
    }>(API_ENDPOINTS.whatsapp.createFromClientGroup, {
      source_group_id: input.sourceGroupId,
      name: input.name,
      support_contacts: input.supportContacts,
      recipient_opt_in_confirmed: input.recipientOptInConfirmed,
      preview_revision: input.previewRevision,
    });
    return data.group;
  },
};
