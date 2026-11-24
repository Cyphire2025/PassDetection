"use client";
import { useMemo, useRef, useState } from "react";
import { useWhatsAppActivityTracker } from "@/features/whatsapp/components/whatsapp-activity-tracker";
import { useDocumentDeliveryPreview, useSendDocumentWhatsAppBroadcast } from "./use-document-distribution";
import type { DocumentDistributionLane } from "../config/document-distribution-lanes";
import { activeDeliverySelection, eligibleDeliveryDocumentIds } from "../components/document-workspace-model";

export function useDocumentWorkspaceDelivery(groupId: string, lane: DocumentDistributionLane, groupName?: string) {
  const { registerActivity } = useWhatsAppActivityTracker();
  const documentType = lane.documentType;
  const sendInFlight = useRef(false);
  const [isSendPreviewOpen, setIsSendPreviewOpen] = useState(false);
  const [deliveryDocumentIds, setDeliveryDocumentIds] = useState<string[] | null>(null);
  const [deliveryResendDocumentIds, setDeliveryResendDocumentIds] = useState<string[]>([]);
  const [deliveryMessageContent1, setDeliveryMessageContent1] = useState<string | null>(null);
  const [deliveryMessageContent2, setDeliveryMessageContent2] = useState<string | null>(null);
  const [deliveryFeedback, setDeliveryFeedback] = useState<string | null>(null);
  const deliveryPreview = useDocumentDeliveryPreview(groupId, documentType, isSendPreviewOpen);
  const sendDocuments = useSendDocumentWhatsAppBroadcast(groupId, documentType);
  const defaultDeliveryDocumentIds = useMemo(
    () => eligibleDeliveryDocumentIds(deliveryPreview.data),
    [deliveryPreview.data],
  );
  const deliverySelection = useMemo(
    () => activeDeliverySelection(deliveryPreview.data, deliveryDocumentIds, deliveryResendDocumentIds),
    [deliveryPreview.data, deliveryDocumentIds, deliveryResendDocumentIds],
  );
  const activeDeliveryDocumentIds = deliverySelection.documentIds;
  const activeDeliveryMessageContent1 =
    deliveryMessageContent1 ?? deliveryPreview.data?.message_content_1 ?? "";
  const activeDeliveryMessageContent2 =
    deliveryMessageContent2 ?? deliveryPreview.data?.message_content_2 ?? "";

  function openDelivery(documentIds: string[] | null = null, resendIds: string[] = []) {
    sendDocuments.reset();
    setDeliveryDocumentIds(documentIds);
    setDeliveryResendDocumentIds(resendIds);
    setDeliveryMessageContent1(null);
    setDeliveryMessageContent2(null);
    setDeliveryFeedback(null);
    setIsSendPreviewOpen(true);
  }

  function sendDelivery() {
    const batchId = deliveryPreview.data?.batch_id;
    const previewToken = deliveryPreview.data?.preview_token;
    if (!batchId || !previewToken || !deliveryPreview.data?.can_send || deliveryPreview.isFetching
      || deliveryPreview.error || sendDocuments.isPending || sendInFlight.current || activeDeliveryDocumentIds.length === 0) return;
    sendInFlight.current = true;
    sendDocuments.mutate(
      {
        batchId,
        documentIds: activeDeliveryDocumentIds,
        resendDocumentIds: deliverySelection.resendDocumentIds,
        messageContent1: activeDeliveryMessageContent1.trim(),
        messageContent2: activeDeliveryMessageContent2.trim(),
        previewToken,
      },
      {
        onSettled: () => { sendInFlight.current = false; },
        onSuccess: (result) => {
          if (result.send_batch_id) {
            registerActivity({
              id: result.send_batch_id,
              kind: "document",
              startedAt: Date.now(),
              title: `${lane.title} broadcast`,
              contextLabel: groupName ?? "Document distribution",
              sourceGroupId: groupId,
              documentType,
              total: result.queued_count,
              queued: result.queued_count,
              sent: 0,
              failed: 0,
              deliveryUnknown: 0,
            });
          }
          setDeliveryFeedback(result.message);
          setIsSendPreviewOpen(false);
          setDeliveryDocumentIds(null);
          setDeliveryResendDocumentIds([]);
        },
      },
    );
  }
  return {
    isSendPreviewOpen, setIsSendPreviewOpen, deliveryDocumentIds, setDeliveryDocumentIds,
    deliveryResendDocumentIds, setDeliveryResendDocumentIds, deliveryMessageContent1, setDeliveryMessageContent1,
    deliveryMessageContent2, setDeliveryMessageContent2, deliveryFeedback, setDeliveryFeedback,
    deliveryPreview, sendDocuments, defaultDeliveryDocumentIds, deliverySelection, activeDeliveryDocumentIds,
    activeDeliveryMessageContent1, activeDeliveryMessageContent2, openDelivery, sendDelivery,
  };
}
