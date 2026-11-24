import type { DocumentDeliveryPreviewRecipient } from "@/types/document-distribution.types";
import { Badge, Button } from "@/components/ui";
import type { DocumentDeliveryPreviewDialogProps } from "./document-delivery-preview-props";

type DeliveryRecipientTableProps = Pick<
  DocumentDeliveryPreviewDialogProps, "onToggleDocument" | "onToggleResend"
> & {
  assignedRecipients: DocumentDeliveryPreviewRecipient[];
  selectedDocumentIdSet: ReadonlySet<string>;
  resendDocumentIdSet: ReadonlySet<string>;
  recipientSelectionBusy: boolean;
};

export function DocumentDeliveryRecipientTable({
  assignedRecipients,
  selectedDocumentIdSet,
  resendDocumentIdSet,
  recipientSelectionBusy,
  onToggleDocument,
  onToggleResend,
}: DeliveryRecipientTableProps) {
  return (
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
            {assignedRecipients.map((row) => {
              const resendSelected = Boolean(
                row.document_id &&
                resendDocumentIdSet.has(row.document_id),
              );
              return (
                <tr
                  key={`${row.passenger_id}:${row.document_id ?? "empty"}`}
                  className={row.eligible || resendSelected ? "bg-white" : "bg-slate-50/60"}
                >
                  <td className="px-4 py-3">
                    {row.delivery_status === "already_sent" && row.resend_allowed && row.document_id ? (
                      <Button
                        type="button"
                        size="sm"
                        variant={resendSelected ? "secondary" : "outline"}
                        disabled={recipientSelectionBusy}
                        onClick={() => onToggleResend(row.document_id as string)}
                      >
                        {resendSelected ? "Resend selected" : "Resend"}
                      </Button>
                    ) : (
                      <input
                        type="checkbox"
                        checked={Boolean(row.document_id && selectedDocumentIdSet.has(row.document_id))}
                        disabled={!row.eligible || !row.document_id || recipientSelectionBusy}
                        onChange={() => row.document_id && onToggleDocument(row.document_id)}
                        aria-label={`Send document to ${row.passenger_name}`}
                        className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                      />
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-semibold text-slate-900">
                      {row.passenger_name}
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      {row.passport_number || "No passport number"}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-800">
                      {row.document_filename || "No document"}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-800">
                      {row.phone_number || "No valid WhatsApp number"}
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      {documentPhoneSourceLabel(row)}
                    </div>
                    {row.broadcast_name && <div className="mt-1 text-xs text-slate-500">Linked broadcast: {row.broadcast_name}</div>}
                  </td>
                  <td className="px-4 py-3">
                    <DeliveryPreviewStatus status={row.delivery_status} />
                    <div className="mt-1 max-w-xs text-xs text-slate-500">
                      {row.reason}
                    </div>
                    {row.error_message && row.delivery_status === "retryable" && (
                      <div className="mt-1 max-w-md text-xs font-medium text-red-700">
                        {row.error_message}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
            {assignedRecipients.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-500">No travellers have an assigned PDF in this section.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function documentPhoneSourceLabel(row: DocumentDeliveryPreviewRecipient) {
  if (!row.phone_number) return "Contact details need review";
  if (row.phone_source === "submission") return "Entered for this traveller";
  if (row.phone_source === "imported_group") return "Imported group number";
  if (row.phone_source === "linked_broadcast" || row.recipient_id) return "Linked broadcast number";
  return "Traveller delivery number";
}

function DeliveryPreviewStatus({ status }: { status: string; }) {
  if (status === "ready") return (
    <Badge variant="success">Ready</Badge>
  );
  if (status === "retryable") return (
    <Badge variant="warning">Retry failed</Badge>
  );
  if (status === "already_sent") return (
    <Badge variant="success">Already sent</Badge>
  );
  if (status === "queued" || status === "processing") return (
    <Badge variant="outline">In progress</Badge>
  );
  if (status === "delivery_unknown") return (
    <Badge variant="warning">Outcome unknown</Badge>
  );
  return (
    <Badge variant="outline">Blocked</Badge>
  );
}
