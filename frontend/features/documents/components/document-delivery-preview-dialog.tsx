import { useMemo, useRef } from "react";
import { X } from "lucide-react";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { ProcessingMotion } from "@/components/shared/processing-motion";
import type { DocumentDeliveryPreviewDialogProps } from "./document-delivery-preview-props";
import { DocumentDeliveryPreviewSummary } from "./document-delivery-preview-summary";
import { DocumentDeliveryMessageFields } from "./document-delivery-message-fields";
import { DocumentDeliveryRecipientTable } from "./document-delivery-recipient-table";
import { DocumentDeliveryPreviewFooter } from "./document-delivery-preview-footer";

export function DocumentDeliveryPreviewDialog({
  preview,
  loading,
  refreshing = false,
  loadError,
  selectedDocumentIds,
  resendDocumentIds,
  sending,
  sendError,
  messageContent1,
  messageContent2,
  onMessageContent1Change,
  onMessageContent2Change,
  onToggleDocument,
  onToggleResend,
  onClose,
  onSend,
  onRefresh,
}: DocumentDeliveryPreviewDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const handleKeyDown = useModalKeyboardBoundary({
    dialogRef,
    isOpen: true,
    canClose: !sending,
    onClose,
  });
  const selectedDocumentIdSet = useMemo(
    () => new Set(selectedDocumentIds),
    [selectedDocumentIds],
  );
  const resendDocumentIdSet = useMemo(
    () => new Set(resendDocumentIds),
    [resendDocumentIds],
  );
  const sampleMessage = [
    "Dear Delegates",
    "Greetings from Global Connect Travels",
    messageContent1,
    messageContent2,
    "Regards,\nTeam Global Connect Travels",
  ].join("\n\n");
  const messageContentValid =
    Boolean(messageContent1.trim()) &&
    Boolean(messageContent2.trim()) &&
    messageContent1.length <= 600 &&
    messageContent2.length <= 600;
  const recipientSelectionBusy = sending || refreshing;
  const assignedRecipients = useMemo(
    () => preview?.recipients.filter((row) => Boolean(row.document_id)) ?? [],
    [preview?.recipients],
  );
  const assignedDocumentCount = preview?.summary.total_documents ?? assignedRecipients.length;
  const deliveryIssues = [
    { label: "Travellers without a number", count: preview?.summary.missing_phone ?? 0 },
    { label: "Documents not saved", count: preview?.summary.unsaved_document ?? 0 },
  ].filter((issue) => issue.count > 0);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm"
      ref={dialogRef}
      onKeyDown={handleKeyDown}
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-labelledby="document-delivery-preview-title"
    >
      <div className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-5">
          <div>
            <h2 id="document-delivery-preview-title" className="text-lg font-semibold text-slate-950">
              Preview WhatsApp document delivery
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              Review only travellers with assigned PDFs in this section. Confirm each PDF and its delivery WhatsApp number before sending.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={sending}
            className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
            aria-label="Close delivery preview"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {loading ? (
            <div className="flex flex-col items-center gap-4 rounded-xl border border-blue-100 bg-blue-50/60 p-5 sm:flex-row sm:gap-6">
              <ProcessingMotion variant="distribution" compact className="w-full shrink-0 sm:w-44" />
              <div className="min-w-0" role="status">
                <p className="text-sm font-semibold text-blue-950">Preparing the delivery preview</p>
                <p className="mt-1 text-sm leading-6 text-slate-600">Checking document assignments and recipient eligibility before you review.</p>
              </div>
            </div>
          ) : loadError ? (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              {loadError.message || "The delivery preview could not be loaded."}
            </div>
          ) : preview ? (
            <div className="space-y-5">
              <DocumentDeliveryPreviewSummary
                preview={preview}
                assignedDocumentCount={assignedDocumentCount}
                refreshing={refreshing}
                deliveryIssues={deliveryIssues}
              />
              <DocumentDeliveryMessageFields
                preview={preview}
                sending={sending}
                messageContent1={messageContent1}
                messageContent2={messageContent2}
                onMessageContent1Change={onMessageContent1Change}
                onMessageContent2Change={onMessageContent2Change}
                sampleMessage={sampleMessage}
              />

              <DocumentDeliveryRecipientTable
                assignedRecipients={assignedRecipients}
                selectedDocumentIdSet={selectedDocumentIdSet}
                resendDocumentIdSet={resendDocumentIdSet}
                recipientSelectionBusy={recipientSelectionBusy}
                onToggleDocument={onToggleDocument}
                onToggleResend={onToggleResend}
              />
            </div>
          ) : null}
        </div>

        <DocumentDeliveryPreviewFooter
          preview={preview}
          sending={sending}
          sendError={sendError}
          loadError={loadError}
          selectedDocumentIds={selectedDocumentIds}
          loading={loading}
          refreshing={refreshing}
          onClose={onClose}
          onSend={onSend}
          onRefresh={onRefresh}
          messageContentValid={messageContentValid}
        />
      </div>
    </div>
  );
}
