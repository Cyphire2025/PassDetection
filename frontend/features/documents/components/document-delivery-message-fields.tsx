import type { DocumentDeliveryPreview } from "@/types/document-distribution.types";
import type { DocumentDeliveryPreviewDialogProps } from "./document-delivery-preview-props";

type DeliveryMessageFieldsProps = Pick<
  DocumentDeliveryPreviewDialogProps,
  | "messageContent1"
  | "messageContent2"
  | "onMessageContent1Change"
  | "onMessageContent2Change"
  | "sending"
> & {
  preview: DocumentDeliveryPreview;
  sampleMessage: string;
};

export function DocumentDeliveryMessageFields({
  preview,
  sending,
  messageContent1,
  messageContent2,
  onMessageContent1Change,
  onMessageContent2Change,
  sampleMessage,
}: DeliveryMessageFieldsProps) {
  return (
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
          {preview.template_name || "Document message"} preview
        </div>
        <div className="mt-3 rounded-lg border border-emerald-100 bg-white p-3 text-xs font-medium text-slate-600">
          PDF document attached individually
        </div>
        <p className="mt-3 whitespace-pre-line [overflow-wrap:anywhere] text-sm leading-6 text-slate-800">
          {sampleMessage}
        </p>
        <p className="mt-2 text-xs text-slate-500">Each passenger receives only the PDF shown in their row.</p>
      </div>
    </div>
  );
}
