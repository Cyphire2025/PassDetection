import { useMemo } from "react";
import { Send, Trash2, X } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import { ProcessingMotion } from "@/components/shared/processing-motion";
import type { DocumentDeliveryPreview } from "@/types/document-distribution.types";

type AbortIncompleteUploadDialogProps = {
  uploadCount: number;
  pending: boolean;
  error: Error | null;
  onClose: () => void;
  onConfirm: () => void;
};

export function AbortIncompleteUploadDialog({
  uploadCount,
  pending,
  error,
  onClose,
  onConfirm,
}: AbortIncompleteUploadDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="abort-incomplete-upload-title"
        className="w-full max-w-lg overflow-hidden rounded-xl bg-white shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-5">
          <div>
            <h2 id="abort-incomplete-upload-title" className="text-lg font-semibold text-slate-900">
              Discard incomplete {uploadCount === 1 ? "upload" : "uploads"}?
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              This permanently removes only the PDFs and partial matches from {uploadCount === 1 ? "this unfinished upload" : `these ${uploadCount} unfinished uploads`}. Completed and saved document lists are not changed.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close dialog"
            className="rounded-full p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
            disabled={pending}
            onClick={onClose}
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="space-y-3 px-6 py-5">
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            After cleanup, you can choose a new PDF selection and Save List will no longer be blocked by these unfinished uploads.
          </div>
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error.message}
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-100 px-6 py-4">
          <Button type="button" variant="secondary" onClick={onClose} disabled={pending}>
            Keep upload
          </Button>
          <Button type="button" variant="danger" onClick={onConfirm} isLoading={pending}>
            <Trash2 className="h-4 w-4" />
            Discard incomplete {uploadCount === 1 ? "upload" : "uploads"}
          </Button>
        </div>
      </div>
    </div>
  );
}

type RemoveAssignmentsDialogProps = {
  passengerCount: number;
  documentCount: number;
  pending: boolean;
  error: Error | null;
  onClose: () => void;
  onKeepFiles: () => void;
  onDeleteFiles: () => void;
};

export function RemoveAssignmentsDialog({
  passengerCount,
  documentCount,
  pending,
  error,
  onClose,
  onKeepFiles,
  onDeleteFiles,
}: RemoveAssignmentsDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="remove-assignments-title"
        className="w-full max-w-xl overflow-hidden rounded-xl bg-white shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-5">
          <div>
            <h2 id="remove-assignments-title" className="text-lg font-semibold text-slate-900">
              Remove document assignments?
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              This removes {documentCount} saved document{documentCount === 1 ? "" : "s"} from{" "}
              {passengerCount} passenger{passengerCount === 1 ? "" : "s"}. Choose what should happen
              to the saved PDF files.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close dialog"
            className="rounded-full p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
            disabled={pending}
            onClick={onClose}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-3 px-6 py-5">
          <button
            type="button"
            disabled={pending}
            onClick={onKeepFiles}
            className="w-full rounded-xl border border-blue-200 bg-blue-50 p-4 text-left transition hover:border-blue-300 disabled:pointer-events-none disabled:opacity-50"
          >
            <div className="font-semibold text-blue-950">Keep saved PDFs</div>
            <div className="mt-1 text-sm leading-5 text-blue-800">
              Remove the passenger assignments and move the PDFs to Needs assignment so they can
              be assigned again later.
            </div>
          </button>
          <button
            type="button"
            disabled={pending}
            onClick={onDeleteFiles}
            className="w-full rounded-xl border border-red-200 bg-red-50 p-4 text-left transition hover:border-red-300 disabled:pointer-events-none disabled:opacity-50"
          >
            <div className="font-semibold text-red-950">Delete saved PDFs</div>
            <div className="mt-1 text-sm leading-5 text-red-800">
              Remove the assignments and permanently delete these saved document files. Delivery
              history remains recorded for audit purposes.
            </div>
          </button>
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error.message}
            </div>
          )}
        </div>

        <div className="flex justify-end border-t border-slate-100 px-6 py-4">
          <Button type="button" variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
}

type DocumentDeliveryPreviewDialogProps = {
  preview: DocumentDeliveryPreview | undefined;
  loading: boolean;
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
};

export function DocumentDeliveryPreviewDialog({
  preview,
  loading,
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
}: DocumentDeliveryPreviewDialogProps) {
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
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm"
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
              Confirm the exact document, passenger, and opted-in WhatsApp number before queueing individual messages.
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
              <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
                <DeliverySummary label="Passengers" value={preview.summary.total_passengers} />
                <DeliverySummary label="Ready" value={preview.summary.ready} tone="success" />
                <DeliverySummary label="Retryable" value={preview.summary.retryable} tone="warning" />
                <DeliverySummary label="Already sent" value={preview.summary.already_sent} />
                <DeliverySummary label="In progress" value={preview.summary.in_progress} />
                <DeliverySummary label="Blocked" value={preview.summary.blocked} tone="danger" />
              </div>

              {preview.configuration_error && (
                <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                  {preview.configuration_error}
                </div>
              )}

              <div className="grid gap-4 lg:grid-cols-2">
                <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4">
                  <div>
                    <label htmlFor="document-message-content-1" className="text-sm font-semibold text-slate-900">
                      Editable text 1
                    </label>
                    <textarea
                      id="document-message-content-1"
                      value={messageContent1}
                      onChange={(event) => onMessageContent1Change(event.target.value)}
                      maxLength={600}
                      rows={3}
                      disabled={sending}
                      className="mt-2 w-full resize-y rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-100"
                    />
                    <p className="mt-1 text-right text-xs text-slate-400">{messageContent1.length}/600</p>
                  </div>
                  <div>
                    <label htmlFor="document-message-content-2" className="text-sm font-semibold text-slate-900">
                      Editable text 2
                    </label>
                    <textarea
                      id="document-message-content-2"
                      value={messageContent2}
                      onChange={(event) => onMessageContent2Change(event.target.value)}
                      maxLength={600}
                      rows={3}
                      disabled={sending}
                      className="mt-2 w-full resize-y rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-100"
                    />
                    <p className="mt-1 text-right text-xs text-slate-400">{messageContent2.length}/600</p>
                  </div>
                </div>
                <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-4">
                  <div className="text-xs font-semibold uppercase tracking-wide text-emerald-800">
                    documents_v1 preview
                  </div>
                  <div className="mt-3 rounded-lg border border-emerald-100 bg-white p-3 text-xs font-medium text-slate-600">
                    PDF document attached individually
                  </div>
                  <p className="mt-3 whitespace-pre-line text-sm leading-6 text-slate-800">{sampleMessage}</p>
                  <p className="mt-2 text-xs text-slate-500">Each passenger receives only the PDF shown in their row.</p>
                </div>
              </div>

              <div className="overflow-hidden rounded-xl border border-slate-200">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[900px] text-left text-sm">
                    <caption className="sr-only">WhatsApp document distribution preview</caption>
                    <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                      <tr>
                        <th scope="col" className="px-4 py-3">Send</th>
                        <th scope="col" className="px-4 py-3">Passenger</th>
                        <th scope="col" className="px-4 py-3">Document</th>
                        <th scope="col" className="px-4 py-3">WhatsApp recipient</th>
                        <th scope="col" className="px-4 py-3">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {preview.recipients.map((row) => {
                        const resendSelected = Boolean(
                          row.document_id &&
                          resendDocumentIdSet.has(row.document_id),
                        );
                        return (
                        <tr key={`${row.passenger_id}:${row.document_id ?? "empty"}`} className={row.eligible || resendSelected ? "bg-white" : "bg-slate-50/60"}>
                          <td className="px-4 py-3">
                            {row.delivery_status === "already_sent" && row.resend_allowed && row.document_id ? (
                              <Button
                                type="button"
                                size="sm"
                                variant={resendSelected ? "secondary" : "outline"}
                                disabled={sending}
                                onClick={() => onToggleResend(row.document_id as string)}
                              >
                                {resendSelected ? "Resend selected" : "Resend"}
                              </Button>
                            ) : (
                              <input
                                type="checkbox"
                                checked={Boolean(row.document_id && selectedDocumentIdSet.has(row.document_id))}
                                disabled={!row.eligible || !row.document_id || sending}
                                onChange={() => row.document_id && onToggleDocument(row.document_id)}
                                aria-label={`Send document to ${row.passenger_name}`}
                                className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                              />
                            )}
                          </td>
                          <td className="px-4 py-3">
                            <div className="font-semibold text-slate-900">{row.passenger_name}</div>
                            <div className="mt-1 text-xs text-slate-500">{row.passport_number || "No passport number"}</div>
                          </td>
                          <td className="px-4 py-3">
                            <div className="font-medium text-slate-800">{row.document_filename || "No document"}</div>
                          </td>
                          <td className="px-4 py-3">
                            <div className="font-medium text-slate-800">{row.phone_number || "Not matched"}</div>
                            <div className="mt-1 text-xs text-slate-500">{row.broadcast_name || "No linked broadcast match"}</div>
                          </td>
                          <td className="px-4 py-3">
                            <DeliveryPreviewStatus status={row.delivery_status} />
                            <div className="mt-1 max-w-xs text-xs text-slate-500">{row.reason}</div>
                            {row.error_message && row.delivery_status === "retryable" && (
                              <div className="mt-1 max-w-md text-xs font-medium text-red-700">
                                {row.error_message}
                              </div>
                            )}
                          </td>
                        </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          ) : null}
        </div>

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
            <div className="flex justify-end gap-3">
              <Button type="button" variant="secondary" onClick={onClose} disabled={sending}>Cancel</Button>
              <Button
                type="button"
                onClick={onSend}
                isLoading={sending}
                disabled={
                  !preview?.can_send ||
                  selectedDocumentIds.length === 0 ||
                  loading ||
                  !messageContentValid
                }
              >
                <Send className="h-4 w-4" />
                Send individually to {selectedDocumentIds.length}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

type DeliverySummaryProps = {
  label: string;
  value: number;
  tone?: "neutral" | "success" | "warning" | "danger";
};

function DeliverySummary({ label, value, tone = "neutral" }: DeliverySummaryProps) {
  const toneClass = tone === "success"
    ? "border-emerald-200 bg-emerald-50 text-emerald-900"
    : tone === "warning"
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : tone === "danger"
        ? "border-red-200 bg-red-50 text-red-900"
        : "border-slate-200 bg-slate-50 text-slate-900";
  return (
    <div className={`rounded-xl border p-3 ${toneClass}`}>
      <div className="text-xs font-medium opacity-70">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
    </div>
  );
}

function DeliveryPreviewStatus({ status }: { status: string }) {
  if (status === "ready") return <Badge variant="success">Ready</Badge>;
  if (status === "retryable") return <Badge variant="warning">Retry failed</Badge>;
  if (status === "already_sent") return <Badge variant="success">Already sent</Badge>;
  if (status === "queued" || status === "processing") return <Badge variant="outline">In progress</Badge>;
  if (status === "delivery_unknown") return <Badge variant="warning">Outcome unknown</Badge>;
  return <Badge variant="outline">Blocked</Badge>;
}
