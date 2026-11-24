import { Loader2 } from "lucide-react";
import type { GroupWhatsAppMatch } from "../api/upload-links.api";
import { MATCH_FILTERS, type MatchFilter } from "./group-whatsapp-tracking-model";
import { BroadcastMatchRow, groupWhatsAppMatchKey, type MatchRowActions } from "./group-whatsapp-match-row";

type Props = MatchRowActions & { rows: GroupWhatsAppMatch[]; isLoading: boolean; error: unknown; filter: MatchFilter };

export function BroadcastMatchTable({
  rows,
  isLoading,
  error,
  filter,
  canManage,
  isActionPending,
  onMarkReplacement,
  onReject,
  onRestore,
}: Props) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 rounded-xl border border-slate-200 py-10 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        Comparing recipients and submissions
      </div>
    );
  }
  if (error) {
    return (
      <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        Recipient comparison could not be loaded.
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500">
        No records match the “{MATCH_FILTERS.find((item) => item.value === filter)?.label}” filter.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="w-full min-w-[1280px] text-left text-sm">
        <caption className="sr-only">WhatsApp recipient identity and submission comparison</caption>
        <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="px-4 py-3">Person / upload</th>
            <th scope="col" className="px-4 py-3">Imported details</th>
            <th scope="col" className="px-4 py-3">Broadcasts</th>
            <th scope="col" className="px-4 py-3">Identification</th>
            <th scope="col" className="px-4 py-3">Submissions</th>
            <th scope="col" className="px-4 py-3">Updated</th>
            {canManage && <th scope="col" className="px-4 py-3">Action</th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row, index) => (
            <BroadcastMatchRow
              key={groupWhatsAppMatchKey(row, index)}
              row={row}
              canManage={canManage}
              isActionPending={isActionPending}
              onMarkReplacement={onMarkReplacement}
              onReject={onReject}
              onRestore={onRestore}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
