import type { DocumentDeliveryPreview } from "@/types/document-distribution.types";

export type DocumentDeliveryPreviewDialogProps = {
  preview: DocumentDeliveryPreview | undefined;
  loading: boolean;
  refreshing?: boolean;
  loadError: Error | null;
  selectedDocumentIds: string[];
  resendDocumentIds: string[];
  sending: boolean;
  sendError: Error | null;
  messageContent1: string;
  messageContent2: string;
  onMessageContent1Change: (value: string) => void;
  onMessageContent2Change: (value: string) => void;
  onToggleDocument: (documentId: string) => void;
  onToggleResend: (documentId: string) => void;
  onClose: () => void;
  onSend: () => void;
  onRefresh?: () => void;
};
