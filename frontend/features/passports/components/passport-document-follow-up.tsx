import { Flag, FlagOff, Loader2 } from "lucide-react";
import type { usePassportDocumentFollowUp } from "./use-passport-document-follow-up";

export function DocumentFollowUpBadge({ flagged }: { flagged?: boolean }) {
  if (!flagged) return null;
  return (
    <span className="mt-1 inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-1 text-xs font-medium text-amber-900">
      <Flag aria-hidden="true" className="h-3 w-3" />
      Document follow-up
    </span>
  );
}

export function DocumentFollowUpActions({ followUp, selectedCount }: {
  followUp: ReturnType<typeof usePassportDocumentFollowUp>;
  selectedCount: number;
}) {
  if (!followUp.canManage) return null;
  const PendingIcon = followUp.isPending ? Loader2 : Flag;
  return (
    <>
      <button
        type="button"
        disabled={followUp.isPending}
        className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        onClick={() => followUp.update(true)}
      >
        <PendingIcon aria-hidden="true" className={`h-4 w-4 shrink-0 text-amber-600 ${followUp.isPending ? "animate-spin" : ""}`} />
        Flag for document follow-up ({selectedCount})
      </button>
      <button
        type="button"
        disabled={followUp.isPending}
        className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        onClick={() => followUp.update(false)}
      >
        <FlagOff aria-hidden="true" className="h-4 w-4 shrink-0 text-slate-500" />
        Clear document follow-up flag ({selectedCount})
      </button>
    </>
  );
}
