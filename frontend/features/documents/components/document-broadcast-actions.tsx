"use client";

import { Send } from "lucide-react";
import { Button } from "@/components/ui";
import type { DistributionDocumentType } from "@/types/document-distribution.types";

export function DocumentBroadcastActions({ onSendDocuments, documentsDisabled = false }: {
  groupId: string;
  documentType: DistributionDocumentType;
  broadcastGroupId?: string;
  onSendDocuments: () => void;
  documentsDisabled?: boolean;
}) {
  return <Button variant="secondary" onClick={onSendDocuments} disabled={documentsDisabled}><Send className="h-4 w-4" />Send WhatsApp Broadcast</Button>;
}
