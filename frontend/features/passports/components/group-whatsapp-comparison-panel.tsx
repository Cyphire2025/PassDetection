import { isDownloadCancelled } from "@/lib/api/download-destination";
import { Button } from "@/components/ui";
import { createRosterRequestId } from "./group-whatsapp-tracking-model";
import { BroadcastMatchTable } from "./group-whatsapp-tracking-table";
import { GroupWhatsAppTrackingFilters } from "./group-whatsapp-tracking-filters";
import type { GroupWhatsAppTrackingModel } from "./use-group-whatsapp-tracking";

type Props = Pick<
  GroupWhatsAppTrackingModel,
  | "groupId"
  | "matchFilter"
  | "setMatchFilter"
  | "broadcastFilter"
  | "setBroadcastFilter"
  | "matchPage"
  | "setMatchPage"
  | "setReplacementRow"
  | "setRejectRow"
  | "setRejectRequestId"
  | "setRestoreRow"
  | "resolutionError"
  | "setResolutionError"
  | "links"
  | "canManage"
  | "rejectUpload"
  | "restoreResolution"
  | "exportTracking"
  | "matchesQuery"
>;

export function GroupWhatsAppComparisonPanel({
  groupId,
  matchFilter,
  setMatchFilter,
  broadcastFilter,
  setBroadcastFilter,
  matchPage,
  setMatchPage,
  setReplacementRow,
  setRejectRow,
  setRejectRequestId,
  setRestoreRow,
  resolutionError,
  setResolutionError,
  links,
  canManage,
  rejectUpload,
  restoreResolution,
  exportTracking,
  matchesQuery,
}: Props) {
  return (
    <div className="space-y-3">
      <GroupWhatsAppTrackingFilters
        groupId={groupId}
        matchFilter={matchFilter}
        setMatchFilter={setMatchFilter}
        broadcastFilter={broadcastFilter}
        setBroadcastFilter={setBroadcastFilter}
        setMatchPage={setMatchPage}
        links={links}
        exportTracking={exportTracking}
        matchesQuery={matchesQuery}
      />

      {exportTracking.error && !isDownloadCancelled(exportTracking.error) && (
        <div
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          This tracking view could not be exported. Refresh and try again.
        </div>
      )}

      <BroadcastMatchTable
        rows={matchesQuery.data?.matches ?? []}
        isLoading={matchesQuery.isLoading || matchesQuery.isFetching}
        error={matchesQuery.error}
        filter={matchFilter}
        canManage={canManage}
        isActionPending={
          rejectUpload.isPending || restoreResolution.isPending
        }
        onMarkReplacement={(row) => {
          setResolutionError(null);
          setReplacementRow(row);
        }}
        onReject={(row) => {
          setResolutionError(null);
          setRejectRequestId(createRosterRequestId());
          setRejectRow(row);
        }}
        onRestore={(row) => {
          setResolutionError(null);
          setRestoreRow(row);
        }}
      />
      {resolutionError && (
        <div
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {resolutionError}
        </div>
      )}
      {matchesQuery.data && matchesQuery.data.total > 0 && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-slate-500">
            Showing {matchesQuery.data.matches.length.toLocaleString()} of{" "}
            {matchesQuery.data.total.toLocaleString()} recipients in this view
          </p>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={matchPage <= 1 || matchesQuery.isFetching}
              onClick={() => setMatchPage((current) => Math.max(1, current - 1))}
            >
              Previous
            </Button>
            <span className="min-w-20 text-center text-xs font-semibold text-slate-600">
              {matchesQuery.data.page} / {Math.max(1, matchesQuery.data.total_pages)}
            </span>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={
                matchPage >= matchesQuery.data.total_pages
                || matchesQuery.isFetching
              }
              onClick={() => setMatchPage((current) => current + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
