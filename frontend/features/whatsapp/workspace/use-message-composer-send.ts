"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ROUTES } from "@/constants/routes";
import { useNormalWhatsAppSend } from "../hooks/use-normal-send";
import { readErrorMessage } from "../components/whatsapp-dialog-ui";
import { useWhatsAppActivityTracker } from "../components/whatsapp-activity-tracker";
import { UncertainWhatsAppSendError } from "../utils/normal-send-storage";
import type { WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";
import type { ComposerVariables, MessageDefinition } from "./composer.api";
import type { useMessageComposerPreview } from "./use-message-composer-preview";

interface SendInput {
  definition: MessageDefinition;
  group: WhatsAppBroadcastGroupDetail;
  image: File | null;
  mutation: ReturnType<typeof useNormalWhatsAppSend<ComposerVariables>>;
  view: Pick<ReturnType<typeof useMessageComposerPreview>, "ready" | "selected" | "draft" | "fields" | "imageId" | "preview" | "count">;
}

export function useMessageComposerSend({ definition, group, image, mutation, view }: SendInput) {
  const { ready, selected, draft, fields, imageId, preview, count } = view;
  const router = useRouter();
  const { registerActivity } = useWhatsAppActivityTracker();
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
    send
  };
}
