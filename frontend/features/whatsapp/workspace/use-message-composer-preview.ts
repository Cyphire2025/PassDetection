"use client";

import { useMemo } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useDebounce } from "@/hooks/use-debounce";
import { whatsappApi, type WhatsAppBroadcastGroupDetail, type WhatsAppMessageDraft } from "../api/whatsapp.api";
import { isRecipientEligible } from "../utils/recipient-delivery";
import type { MessageDefinition } from "./composer.api";
import type { ComposerState } from "./message-composer-state";
import { composerFieldState } from "./composer-field-state";
import { resolveComposerDraft } from "./composer-draft";

interface PreviewInput {
  definition: MessageDefinition;
  group: WhatsAppBroadcastGroupDetail;
  state: ComposerState;
  image: File | null;
  imageError: string | null;
  mutation: { isPending: boolean };
}

export function useMessageComposerPreview({ definition, group, state, image, imageError, mutation }: PreviewInput) {
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
  const { activeLinks, reminderGroupId, audienceReady, selectedIds, selectedIdSet, draft } = resolveComposerDraft(definition, group, state, eligible);

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
  const { fields, fieldErrors, fieldReady } = composerFieldState(definition, state, preview);
  const audienceIds = preview.data?.audience_recipient_ids
    ? new Set(preview.data.audience_recipient_ids)
    : null;
  const audience = eligible.filter(
    (recipient) => !audienceIds || audienceIds.has(recipient.id),
  );
  const selected = audience.filter((recipient) =>
    selectedIdSet.has(recipient.id),
  );
  const imageId = image ? null : (preview.data?.header_image_id ?? null);
  const count =
    selectedIds.length === 0
      ? 0
      : current
        ? (preview.data?.eligible_recipient_count ?? 0)
        : null;

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
  return {
    draft,
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
    imageId,
    activeLinks,
    reminderGroupId,
    audienceReady
  };
}
