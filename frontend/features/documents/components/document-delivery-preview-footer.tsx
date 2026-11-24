import { RefreshCw, Send } from "lucide-react";
import { Button } from "@/components/ui";
import { ProcessingMotion } from "@/components/shared/processing-motion";
import type { DocumentDeliveryPreviewDialogProps } from "./document-delivery-preview-props";

type DeliveryPreviewFooterProps = Pick<
  DocumentDeliveryPreviewDialogProps,
  | "preview"
  | "sending"
  | "sendError"
  | "loadError"
  | "selectedDocumentIds"
  | "loading"
  | "onClose"
  | "onSend"
  | "onRefresh"
> & {
  refreshing: boolean;
  messageContentValid: boolean;
};

export function DocumentDeliveryPreviewFooter({
  preview,
  sending,
  sendError,
  loadError,
  selectedDocumentIds,
  loading,
  refreshing,
  onClose,
  onSend,
  onRefresh,
  messageContentValid,
}: DeliveryPreviewFooterProps) {
  return (
    <div className="border-t border-slate-200 px-6 py-4">
      {sending && (
        <div className="mb-4 flex flex-col items-center gap-3 rounded-xl border border-blue-100 bg-blue-50/60 p-3 sm:flex-row sm:gap-5">
          <ProcessingMotion variant="distribution" compact className="w-full shrink-0 sm:w-36" />
          <div className="min-w-0" role="status">
            <p className="text-sm font-semibold text-blue-950">Queueing document messages</p>
            <p className="mt-1 text-sm leading-6 text-slate-600">Preparing {selectedDocumentIds.length} selected {selectedDocumentIds.length === 1 ? "document" : "documents"} for individual delivery. Delivery status will update separately.</p>
          </div>
        </div>
      )}
      {(sendError || loadError) && (
        <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {(sendError || loadError)?.message}
        </div>
      )}
      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-slate-500">
          Successful and uncertain deliveries are excluded automatically to prevent duplicates.
        </p>
        <div className="flex flex-wrap justify-end gap-3">
          {onRefresh && (
            <Button type="button" variant="outline" onClick={onRefresh} disabled={sending || loading || refreshing}>
              <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} aria-hidden="true" />
              {refreshing ? "Refreshing" : "Refresh preview"}
            </Button>
          )}
          <Button type="button" variant="secondary" data-dialog-initial-focus onClick={onClose} disabled={sending}>Cancel</Button>
          <Button
            type="button"
            onClick={onSend}
            isLoading={sending}
            disabled={
              !preview?.can_send ||
              !preview?.preview_token ||
              selectedDocumentIds.length === 0 ||
              loading ||
              refreshing ||
              Boolean(loadError) ||
              !messageContentValid
            }
          >
            <Send className="h-4 w-4" />
            Send individually to {selectedDocumentIds.length}
          </Button>
        </div>
      </div>
    </div>
  );
}
