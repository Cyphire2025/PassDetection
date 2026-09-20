import type { WhatsAppSourceGroupPreview } from "../api/whatsapp-source-groups.api";
import { SourceContactTable } from "./whatsapp-source-contact-table";

export function SourceGroupContactPreview({ preview }: { preview: WhatsAppSourceGroupPreview }) {
  const contacts = preview.contacts ?? preview.recipients.map((recipient, index) => ({
    source_submission_id: recipient.source_submission_id ?? String(index),
    name: recipient.name ?? "", phone_number: recipient.phone_number,
    normalized_phone_number: recipient.phone_number, issue: null, imported_fields: recipient.imported_fields ?? {},
  }));
  const attentionCount = preview.needs_attention_count ?? Math.max(0, preview.excluded_count - preview.excluded_counts.duplicate_phone);
  const sharedCount = preview.shared_phone_count ?? preview.excluded_counts.duplicate_phone;
  return (
    <section className="space-y-3" aria-label="Contact import preview">
      {preview.source_import_only && <span className="inline-flex rounded-md bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">Import only</span>}
      <div className="grid grid-cols-3 gap-2 rounded-xl border border-slate-200 bg-slate-50 p-4">
        {[
          ["Travellers", preview.total_submissions],
          ["Delivery numbers", preview.recipient_count],
          ["Need attention", attentionCount],
        ].map(([label, count]) => <div key={label}><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-xl font-semibold tabular-nums text-slate-900">{count}</p></div>)}
      </div>
      <p className="text-sm leading-relaxed text-slate-600">
        Every traveller row is kept. Shared WhatsApp numbers receive one message per send.
        {sharedCount > 0 && ` ${sharedCount} additional traveller${sharedCount === 1 ? " shares" : "s share"} a number already in this list.`}
      </p>
      {attentionCount > 0 && <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
        {attentionCount} traveller {attentionCount === 1 ? "row needs" : "rows need"} attention. These rows stay in the list. Review their contact status and correct the source details where needed before delivery.
      </p>}
      {contacts.length > 0 ? <SourceContactTable contacts={contacts} /> : <p className="rounded-lg border border-slate-200 p-4 text-sm text-slate-600">No traveller rows to import. Choose another group or add travellers to this group, then refresh the preview.</p>}
      <p className="text-xs leading-relaxed text-slate-500">
        Names combine given name and surname. Numbers use the group’s saved WhatsApp contact data, including the Verified WhatsApp Numbers column or the Upload Phone column in older imports.
        {preview.source_import_only ? " This broadcast stays synced with the Excel import group." : " This broadcast stays synced with the group, with passport submission tracking available from the group page."}
      </p>
    </section>
  );
}
