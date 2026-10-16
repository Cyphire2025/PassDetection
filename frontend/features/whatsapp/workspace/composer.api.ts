import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import {
  whatsappApi,
  type WhatsAppMessageDraft,
  type WhatsAppMessageType,
  type WhatsAppSendResponse,
} from "../api/whatsapp.api";
import type { WhatsAppSendIntent } from "../utils/normal-send-intent";

export interface MessageField {
  key:
    | "message_content"
    | "passport_intro"
    | "passport_link"
    | "group_invite_link";
  label: string;
  kind: "textarea" | "url" | "text";
  required: boolean;
  max_length: number;
}
export interface MessageDefinition {
  id: string;
  message_type: WhatsAppMessageType;
  label: string;
  description: string;
  category: string;
  image_required: boolean;
  audience: "standard" | "reminder" | "update";
  repeatable: boolean;
  fields: MessageField[];
}
export type ComposerVariables = {
  groupId: string;
  recipientIds: string[] | null;
  image: File | null;
  draft: WhatsAppMessageDraft;
};

export const composerApi = {
  passengerLinks: async (groupId: string, signal?: AbortSignal) => {
    const { data } = await apiClient.get<
      { group_id: string; passenger_id: string }[]
    >(
      `${API_ENDPOINTS.whatsapp.groups}/${encodeURIComponent(groupId)}/passenger-links`,
      { signal },
    );
    return data;
  },
  catalog: async (signal?: AbortSignal) => {
    const { data } = await apiClient.get<MessageDefinition[]>(
      `${API_ENDPOINTS.whatsapp.groups.replace(/\/groups$/, "")}/message-catalog`,
      { signal },
    );
    return data;
  },
  send: async (variables: ComposerVariables, intent: WhatsAppSendIntent) => {
    const imageId = variables.image
      ? await intent.resolveImage(
          async () =>
            (
              await whatsappApi.uploadWelcomeImage(
                variables.groupId,
                variables.image!,
              )
            ).media_id,
        )
      : variables.draft.header_image_id;
    const payload = {
      ...variables.draft,
      recipient_ids: variables.recipientIds,
      header_image_id: imageId ?? null,
    };
    // Preview sampling must never enter the strict dispatch request contract.
    delete payload.recipient_id;
    delete payload.resend_recipient_id;
    await intent.bind(variables.groupId, payload);
    const { data } = await apiClient.post<WhatsAppSendResponse>(
      API_ENDPOINTS.whatsapp.send(variables.groupId),
      payload,
      { headers: { "Idempotency-Key": intent.key } },
    );
    return data;
  },
};
