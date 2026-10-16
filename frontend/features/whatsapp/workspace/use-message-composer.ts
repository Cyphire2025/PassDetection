"use client";

import { ROUTES } from "@/constants/routes";
import { useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useDebounce } from "@/hooks/use-debounce";
import { whatsappApi, type WhatsAppMessageDraft } from "../api/whatsapp.api";
import { useNormalWhatsAppSend } from "../hooks/use-normal-send";
import { isRecipientEligible } from "../utils/recipient-delivery";
import { validWhatsAppGroupInviteLink } from "../utils/group-invite";
import { UncertainWhatsAppSendError } from "../utils/normal-send-storage";
import { readErrorMessage } from "../components/whatsapp-dialog-ui";
import { useWhatsAppActivityTracker } from "../components/whatsapp-activity-tracker";
import { useBroadcast } from "./broadcast-workspace-shell";
import {
  composerApi,
  type ComposerVariables,
  type MessageDefinition,
  type MessageField,
} from "./composer.api";

export interface ComposerState {
  fields: Partial<Record<MessageField["key"], string>>;
  recipientIds: string[] | null;
  previewRecipientId: string | null;
  reminderAudience: "all" | "not_submitted";
  reminderGroupId: string | null;
  submission: "all" | "submitted" | "not_submitted";
  distribution: "all" | "sent" | "pending";
  documentType: string;
  supportContactId: string | null;
  includePreviousRecipients: boolean;
}

export function useMessageComposer(definition: MessageDefinition) {
  const group = useBroadcast();
  const router = useRouter();
  const { registerActivity } = useWhatsAppActivityTracker();
  const [state, setState] = useState<ComposerState>({
    fields: {},
    recipientIds: null,
    previewRecipientId: null,
    reminderAudience: "all",
    reminderGroupId: null,
    submission: "all",
    distribution: "all",
    documentType: "visa",
    supportContactId: group.support_contacts[0]?.id ?? null,
    includePreviousRecipients: false,
  });
  const [image, setImage] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const imageUrl = useRef<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recovery, setRecovery] = useState<ComposerVariables | null>(null);
  const [reviewedSend, setReviewedSend] = useState<{
    message: string;
    count: number;
  } | null>(null);
  const [uncertain, setUncertain] = useState<UncertainWhatsAppSendError | null>(
    null,
  );
  const sending = useRef(false);
  const mutation = useNormalWhatsAppSend(
    definition.message_type,
    composerApi.send,
  );
  const eligible = useMemo(
    () =>
      group.recipients.filter((recipient) =>
        isRecipientEligible(
          recipient,
          definition.message_type,
          state.includePreviousRecipients,
        ),
      ),
    [
      group.recipients,
      definition.message_type,
      state.includePreviousRecipients,
    ],
  );
  const activeLinks =
    group.linked_client_groups?.filter((item) => item.status === "active") ??
    [];
  const reminderGroupId =
    state.reminderGroupId ??
    (activeLinks.length === 1 ? activeLinks[0].id : null);
  const audienceReady =
    state.reminderAudience !== "not_submitted" || Boolean(reminderGroupId);
  const selectedIds =
    state.recipientIds ?? eligible.map((recipient) => recipient.id);
  const draft: WhatsAppMessageDraft = {
    message_type: definition.message_type,
    ...state.fields,
    ...(definition.message_type === "passport_link"
      ? { include_previous_recipients: state.includePreviousRecipients }
      : {}),
    recipient_ids: selectedIds.length
      ? selectedIds
      : eligible.map((recipient) => recipient.id),
    recipient_id:
      state.previewRecipientId && selectedIds.includes(state.previewRecipientId)
        ? state.previewRecipientId
        : null,
    support_contact_ids:
      definition.message_type === "passport_link" && state.supportContactId
        ? [state.supportContactId]
        : null,
    ...(definition.audience === "reminder"
      ? {
          audience: state.reminderAudience,
          audience_client_group_id:
            state.reminderAudience === "not_submitted" ? reminderGroupId : null,
        }
      : {}),
    ...(definition.audience === "update"
      ? {
          update_submission: state.submission,
          update_distribution: state.distribution,
          update_document_type: state.documentType,
        }
      : {}),
  };
  const currentKey = JSON.stringify(draft);
  const debouncedKey = useDebounce(currentKey, 300);
  const debouncedDraft = JSON.parse(debouncedKey) as WhatsAppMessageDraft;
  const revision = useMemo(
    () =>
      group.recipients.map((recipient) => [
        recipient.id,
        recipient.normalized_phone_number,
        recipient.welcome_status,
        recipient.message_statuses,
      ]),
    [group.recipients],
  );
  const preview = useQuery({
    queryKey: [
      "whatsapp",
      "composer-preview",
      group.id,
      debouncedDraft,
      revision,
    ],
    queryFn: ({ signal }) =>
      whatsappApi.previewMessage(group.id, debouncedDraft, signal),
    enabled: !group.is_archived && audienceReady && eligible.length > 0,
    placeholderData: keepPreviousData,
    gcTime: 0,
    retry: false,
  });
  const current = Boolean(
    preview.data &&
      currentKey === debouncedKey &&
      !preview.isPlaceholderData &&
      !preview.isFetching &&
      !preview.error,
  );
  const fields = Object.fromEntries(
    definition.fields.map((field) => [
      field.key,
      state.fields[field.key] ?? preview.data?.[field.key] ?? "",
    ]),
  ) as Partial<Record<MessageField["key"], string>>;
  const audienceIds = preview.data?.audience_recipient_ids
    ? new Set(preview.data.audience_recipient_ids)
    : null;
  const audience = eligible.filter(
    (recipient) => !audienceIds || audienceIds.has(recipient.id),
  );
  const selected = audience.filter((recipient) =>
    selectedIds.includes(recipient.id),
  );
  const imageId = image ? null : (preview.data?.header_image_id ?? null);
  const count =
    selectedIds.length === 0
      ? 0
      : current
        ? (preview.data?.eligible_recipient_count ?? 0)
        : null;
  const fieldErrors = Object.fromEntries(
    definition.fields.flatMap((field) => {
      const value = fields[field.key]?.trim() ?? "";
      if (value.length > field.max_length)
        return [[field.key, `Use at most ${field.max_length} characters.`]];
      if (!value || field.kind !== "url") return [];
      if (field.key === "group_invite_link")
        return validWhatsAppGroupInviteLink(value)
          ? []
          : [
              [
                field.key,
                "Paste an official invite beginning with https://chat.whatsapp.com/.",
              ],
            ];
      try {
        const url = new URL(value);
        if (["https:", "http:"].includes(url.protocol)) return [];
      } catch {
        /* display a field-level validation message */
      }
      return [[field.key, "Enter a complete http or https link."]];
    }),
  );
  const fieldReady =
    Object.keys(fieldErrors).length === 0 &&
    definition.fields.every(
      (field) => !field.required || Boolean(fields[field.key]?.trim()),
    );
  const ready = Boolean(
    current &&
      selected.length > 0 &&
      fieldReady &&
      (!definition.image_required || image || imageId) &&
      count &&
      !preview.data?.welcome_required_count &&
      preview.data?.template_name &&
      group.recipient_opt_in_confirmed &&
      !group.is_archived &&
      !mutation.isPending &&
      !imageError,
  );
  useEffect(
    () => () => {
      if (imageUrl.current) URL.revokeObjectURL(imageUrl.current);
    },
    [],
  );
  const selectImage = (file: File) => {
    if (
      !["image/jpeg", "image/png"].includes(file.type) ||
      file.size > 5 * 1024 * 1024
    ) {
      setImageError("Choose a JPEG or PNG image, 5 MB or smaller.");
      return;
    }
    if (imageUrl.current) URL.revokeObjectURL(imageUrl.current);
    imageUrl.current = URL.createObjectURL(file);
    setImagePreview(imageUrl.current);
    setImage(file);
    setImageError(null);
  };
  const send = async (retryPrevious = false) => {
    if (sending.current || (!ready && !(retryPrevious && recovery))) return;
    sending.current = true;
    setError(null);
    const variables: ComposerVariables =
      retryPrevious && recovery
        ? recovery
        : {
            groupId: group.id,
            recipientIds: selected.map((recipient) => recipient.id),
            image,
            draft: {
              ...draft,
              ...fields,
              recipient_id: undefined,
              resend_recipient_id: undefined,
              header_image_id: imageId,
            },
          };
    try {
      if (!retryPrevious)
        setReviewedSend({
          message: preview.data?.rendered_message ?? "",
          count: selected.length,
        });
      const startedAt = Date.now();
      const result = await mutation.mutateAsync(variables);
      setRecovery(null);
      setReviewing(false);
      if (result.batch_id) {
        registerActivity({
          id: result.batch_id,
          kind: "broadcast",
          messageType: definition.message_type,
          title: definition.label,
          contextLabel: group.name,
          sourceGroupId: group.id,
          documentType: null,
          startedAt,
          total:
            result.queued +
            result.sent +
            result.failed +
            result.delivery_unknown,
          queued: result.queued,
          sent: result.sent,
          failed: result.failed,
          deliveryUnknown: result.delivery_unknown,
          skippedAlreadySent: result.skipped_already_sent,
          skippedInProgress: result.skipped_in_progress,
          skippedDeliveryUnknown: result.skipped_delivery_unknown,
        });
        router.push(
          `${ROUTES.dashboard.whatsappBroadcastHistory(group.id)}?message=${encodeURIComponent(result.batch_id)}`,
        );
      } else
        setError(
          "No new messages were queued. Refresh the audience to check its latest delivery state.",
        );
    } catch (cause) {
      if (cause instanceof UncertainWhatsAppSendError) {
        setUncertain(cause);
        setRecovery(null);
      } else setRecovery(variables);
      setError(
        readErrorMessage(
          cause,
          "The send has not been confirmed. Check the same request before starting another send.",
        ),
      );
    } finally {
      sending.current = false;
    }
  };
  return {
    group,
    definition,
    state,
    setState,
    fields,
    fieldErrors,
    eligible,
    audience,
    selected,
    selectedIds,
    preview,
    current,
    ready,
    count,
    image,
    imageId,
    imagePreview,
    imageError,
    selectImage,
    reviewing,
    setReviewing,
    error,
    recovery,
    reviewedMessage: recovery
      ? reviewedSend?.message
      : preview.data?.rendered_message,
    reviewedCount: recovery ? reviewedSend?.count : (count ?? selected.length),
    uncertain,
    startSeparateMessage: () => {
      uncertain?.startNew();
      setUncertain(null);
      setRecovery(null);
      setError(null);
      setReviewing(false);
    },
    send,
    pending: mutation.isPending,
    activeLinks,
    reminderGroupId,
    audienceReady,
  };
}
