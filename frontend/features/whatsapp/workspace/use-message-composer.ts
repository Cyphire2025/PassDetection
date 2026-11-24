"use client";

import { useState } from "react";
import { useNormalWhatsAppSend } from "../hooks/use-normal-send";
import { useBroadcast } from "./broadcast-workspace-shell";
import { composerApi, type MessageDefinition } from "./composer.api";
import type { ComposerState } from "./message-composer-state";
import { useComposerHeaderImage } from "./use-composer-header-image";
import { useMessageComposerPreview } from "./use-message-composer-preview";
import { useMessageComposerSend } from "./use-message-composer-send";

export type { ComposerState } from "./message-composer-state";

export function useMessageComposer(definition: MessageDefinition) {
  const group = useBroadcast();
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
  const { image, imagePreview, imageError, selectImage } = useComposerHeaderImage();
  const mutation = useNormalWhatsAppSend(
    definition.message_type,
    composerApi.send,
  );
  const view = useMessageComposerPreview({ definition, group, state, image, imageError, mutation });
  const {
    fields, fieldErrors, eligible, audience, selected, selectedIds,
    preview, current, ready, count, imageId, activeLinks,
    reminderGroupId, audienceReady,
  } = view;
  const {
    reviewing, setReviewing, error, recovery, reviewedMessage,
    reviewedCount, uncertain, startSeparateMessage, send,
  } = useMessageComposerSend({ definition, group, image, mutation, view });
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
    reviewedMessage,
    reviewedCount,
    uncertain,
    startSeparateMessage,
    send,
    pending: mutation.isPending,
    activeLinks,
    reminderGroupId,
    audienceReady
  };
}
