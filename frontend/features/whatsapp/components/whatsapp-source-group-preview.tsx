import type { WhatsAppSourceGroupPreview } from "../api/whatsapp-source-groups.api";

const skippedLabels: Record<keyof WhatsAppSourceGroupPreview["excluded_counts"], string> = {
  missing_phone: "Missing WhatsApp number",
  invalid_phone: "Invalid WhatsApp number",
  unverified_phone: "No verified WhatsApp contact",
  missing_name: "Missing name",
  name_too_long: "Name exceeds the supported length",
  duplicate_phone: "Duplicate WhatsApp number",
};

export function SourceGroupContactPreview({ preview }: { preview: WhatsAppSourceGroupPreview }) {
  return (
    <section className="space-y-3" aria-label="Contact import preview">
      <div className="grid grid-cols-3 gap-2 rounded-xl border border-slate-200 bg-slate-50 p-4">
        {[
          ["Submissions", preview.total_submissions],
          ["Ready to import", preview.recipient_count],
          ["Skipped", preview.excluded_count],
        ].map(([label, count]) => (
          <div key={label}>
            <p className="text-xs text-slate-500">{label}</p>
            <p className="mt-1 text-xl font-semibold tabular-nums text-slate-900">{count}</p>
          </div>
        ))}
      </div>
      {preview.excluded_count > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          <p className="font-medium">Some submissions will be skipped</p>
          <ul className="mt-2 grid gap-1 sm:grid-cols-2">
            {Object.entries(preview.excluded_counts).filter(([, count]) => count > 0).map(([reason, count]) => (
              <li key={reason}>{skippedLabels[reason as keyof typeof skippedLabels]}: {count}</li>
            ))}
          </ul>
        </div>
      )}
      {preview.recipient_count > 0 ? (
        <div className="max-h-64 overflow-auto rounded-lg border border-slate-200" tabIndex={0} aria-label="Recipients to import" role="region">
          <table className="w-full table-fixed text-left text-sm">
            <caption className="sr-only">Recipients to import from {preview.source_group_name}</caption>
            <thead className="sticky top-0 bg-slate-50 text-xs text-slate-500">
              <tr><th className="px-3 py-2 font-medium" scope="col">Full name</th><th className="px-3 py-2 font-medium" scope="col">Verified WhatsApp Numbers</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {preview.recipients.map((recipient) => (
                <tr key={recipient.phone_number}>
                  <td className="break-words px-3 py-2 text-slate-800">{recipient.name}</td>
                  <td className="break-all px-3 py-2 tabular-nums text-slate-600">{recipient.phone_number}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="rounded-lg border border-slate-200 p-4 text-sm text-slate-600">
          No eligible contacts to import. Choose another group or update the missing contact details in this group, then refresh the preview.
        </p>
      )}
      <p className="text-xs leading-relaxed text-slate-500">
        Names combine given name and surname. Numbers come from the group’s Verified WhatsApp Numbers column; each number is imported once.
        The new broadcast will be linked to this group automatically.
      </p>
    </section>
  );
}
