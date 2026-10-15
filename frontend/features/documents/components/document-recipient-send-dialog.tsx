"use client";

import { useState } from "react";
import type { DistributionDocumentType } from "@/types/document-distribution.types";
import { useDocumentDeliveryPreview, useSendDocumentWhatsAppBroadcast } from "../hooks/use-document-distribution";
import { DocumentDeliveryPreviewDialog } from "./document-workspace-dialogs";
import { activeDeliverySelection, eligibleDeliveryDocumentIds, updateSelectedDocumentIds } from "./document-workspace-model";

export function DocumentRecipientSendDialog({ groupId, documentType, broadcastGroupId, initialResendId, initialDocumentIds, onClose, onSent }: {
  groupId: string; documentType: DistributionDocumentType; broadcastGroupId: string;
  initialResendId?: string; initialDocumentIds?: string[]; onClose: () => void; onSent: (message: string) => void;
}) {
  const preview = useDocumentDeliveryPreview(groupId, documentType, true, broadcastGroupId);
  const send = useSendDocumentWhatsAppBroadcast(groupId, documentType, broadcastGroupId);
  const [selected, setSelected] = useState<string[] | null>(initialResendId ? [initialResendId] : initialDocumentIds ?? null);
  const [resends, setResends] = useState<string[]>(initialResendId ? [initialResendId] : []);
  const [content1, setContent1] = useState<string | null>(null);
  const [content2, setContent2] = useState<string | null>(null);
  const message1 = content1 ?? preview.data?.message_content_1 ?? "";
  const message2 = content2 ?? preview.data?.message_content_2 ?? "";
  const selection = activeDeliverySelection(preview.data, selected, resends);
  const defaultIds = eligibleDeliveryDocumentIds(preview.data);
  return <DocumentDeliveryPreviewDialog preview={preview.data} loading={preview.isLoading} refreshing={preview.isFetching}
    loadError={preview.error} selectedDocumentIds={selection.documentIds} resendDocumentIds={selection.resendDocumentIds}
    sending={send.isPending} sendError={send.error} messageContent1={message1} messageContent2={message2}
    onMessageContent1Change={setContent1} onMessageContent2Change={setContent2}
    onRefresh={() => void preview.refetch()} onClose={() => { if (!send.isPending) onClose(); }}
    onToggleDocument={id => { setSelected(current => { const values = current ?? defaultIds; return updateSelectedDocumentIds(values, [id], !values.includes(id)); }); setResends(current => current.filter(value => value !== id)); }}
    onToggleResend={id => { const removing = resends.includes(id); setResends(current => updateSelectedDocumentIds(current, [id], !removing)); setSelected(current => updateSelectedDocumentIds(current ?? defaultIds, [id], !removing)); }}
    onSend={() => {
      const data = preview.data;
      if (!data?.batch_id || !data.preview_token || !data.can_send || preview.isFetching || preview.error || send.isPending || !selection.documentIds.length) return;
      send.mutate({ batchId: data.batch_id, previewToken: data.preview_token, documentIds: selection.documentIds, resendDocumentIds: selection.resendDocumentIds, messageContent1: message1.trim(), messageContent2: message2.trim() }, { onSuccess: result => onSent(result.message) });
    }} />;
}
