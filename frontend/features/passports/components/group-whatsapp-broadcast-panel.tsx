"use client";

import { AlertCircle, ArrowLeft, CheckCircle2, CircleHelp, Download, Link2, Loader2, MessageCircle, UserRoundCheck, UserRoundX, Users } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import { isDownloadCancelled } from "@/lib/api/download-destination";
import { WorkspacePageHeader } from "@/components/shared/workspace-ui";
import { Button, Card, CardContent, ConfirmDialog, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { canAccessWhatsAppBroadcasts } from "@/lib/utils/role-access";
import { selectHasHydrated, selectUserRole, useAuthStore } from "@/stores/auth.store";
import type { GroupWhatsAppMatch } from "../api/upload-links.api";
import { useExportWhatsAppTracking } from "../hooks/use-passports";
import { useGroupWhatsAppLinks, useGroupWhatsAppMatches, useRejectUnidentifiedUpload, useRestoreRosterResolution } from "../hooks/use-upload-links";
import { broadcastMatchingSummary } from "./whatsapp-match-field-selector";
import { GroupWhatsAppTrackingGate } from "./group-whatsapp-tracking-gate";
import { MATCH_FILTERS, type MatchFilter, rowPrimaryName, createRosterRequestId } from "./group-whatsapp-tracking-model";
import { TrackingStat, BroadcastMatchTable } from "./group-whatsapp-tracking-table";
import { ReplacementDialog, ManageBroadcastsDialog } from "./group-whatsapp-dialogs";

import { GroupWhatsAppSummary } from "./group-whatsapp-summary";

interface GroupWhatsAppBroadcastPanelProps {
  groupId: string;
  readOnly?: boolean;
}

export function GroupWhatsAppBroadcastPanel({
  groupId,
  readOnly = false,
}: GroupWhatsAppBroadcastPanelProps) {
  return (
    <GroupWhatsAppBroadcastWorkspace
      groupId={groupId}
      readOnly={readOnly}
      mode="summary"
    />
  );
}

export function GroupWhatsAppBroadcastTrackingPage({
  groupId,
}: {
  groupId: string;
}) {
  const router = useRouter();
  const hasHydrated = useAuthStore(selectHasHydrated);
  const role = useAuthStore(selectUserRole);
  const canAccessWhatsApp = canAccessWhatsAppBroadcasts(role);

  useEffect(() => {
    if (!hasHydrated || role === null || canAccessWhatsApp) return;
    router.replace(
      (role === "agency_coordinator"
        ? ROUTES.coordinator
        : ROUTES.dashboard.passports),
    );
  }, [canAccessWhatsApp, hasHydrated, role, router]);

  if (!hasHydrated || !canAccessWhatsApp) return null;

  return (
    <GroupWhatsAppTrackingGate groupId={groupId}>
    <div className="space-y-5">
      <WorkspacePageHeader
        title="WhatsApp Submission Tracking"
        description="Compare broadcast recipients with passport submissions and review unmatched records."
        icon={MessageCircle}
        accent="emerald"
        actions={(
          <IntentPrefetchLink
            href={ROUTES.dashboard.passportGroup(groupId)}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-4 text-sm font-semibold text-white transition hover:bg-white/15"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back to group
          </IntentPrefetchLink>
        )}
      />
      <GroupWhatsAppBroadcastWorkspace groupId={groupId} mode="tracking" />
    </div>
    </GroupWhatsAppTrackingGate>
  );
}

function GroupWhatsAppBroadcastWorkspace({
  groupId,
  readOnly = false,
  mode,
}: GroupWhatsAppBroadcastPanelProps & {
  mode: "summary" | "tracking";
}) {
  const [matchFilter, setMatchFilter] = useState<MatchFilter>("all");
  const [broadcastFilter, setBroadcastFilter] = useState("all");
  const [matchPage, setMatchPage] = useState(1);
  const [isManaging, setIsManaging] = useState(false);
  const [replacementRow, setReplacementRow] = (
    useState<GroupWhatsAppMatch | null>(null)
  );
  const [rejectRow, setRejectRow] = useState<GroupWhatsAppMatch | null>(null);
  const [rejectRequestId, setRejectRequestId] = useState<string | null>(null);
  const [restoreRow, setRestoreRow] = useState<GroupWhatsAppMatch | null>(null);
  const [resolutionError, setResolutionError] = useState<string | null>(null);
  const matchPageSize = 50;
  const { data: links, isLoading: linksLoading, error: linksError } = (
    useGroupWhatsAppLinks(groupId)
  );
  const hasLinkedBroadcasts = (links?.broadcast_count ?? 0) > 0;
  const canManage = Boolean(links?.can_manage) && !readOnly;
  const rejectUpload = useRejectUnidentifiedUpload(groupId);
  const restoreResolution = useRestoreRosterResolution(groupId);
  const exportTracking = useExportWhatsAppTracking();
  const matchesQuery = useGroupWhatsAppMatches(
    groupId,
    {
      status: matchFilter,
      sort_by: "name",
      sort_order: "asc",
      page: matchPage,
      page_size: matchPageSize,
      ...(broadcastFilter === "all"
        ? {}
        : { broadcast_id: broadcastFilter }),
    },
    mode === "tracking" && hasLinkedBroadcasts,
  );
  const totalRecipientCount = matchesQuery.data?.counts.total_recipients
    ?? (broadcastFilter === "all" ? links?.recipient_count ?? 0 : null);
  const submittedRecipientCount = (
    matchesQuery.data?.counts.submitted_count ?? null
  );
  const submissionRate = submittedRecipientCount !== null
    && totalRecipientCount !== null
    && totalRecipientCount > 0
    ? Math.round((submittedRecipientCount / totalRecipientCount) * 100)
    : null;

  useEffect(() => {
    const totalPages = matchesQuery.data?.total_pages;
    if (!totalPages || matchPage <= totalPages) return;
    const timer = window.setTimeout(() => {
      setMatchPage(Math.max(1, totalPages));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [matchPage, matchesQuery.data?.total_pages]);

  useEffect(() => {
    if (
      broadcastFilter === "all"
      || links?.broadcasts.some(
        (broadcast) => broadcast.id === broadcastFilter,
      )
    ) {
      return;
    }
    const timer = window.setTimeout(() => {
      setBroadcastFilter("all");
      setMatchPage(1);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [broadcastFilter, links?.broadcasts]);

  if (linksLoading) {
    return <Skeleton className="h-52 w-full rounded-xl" />;
  }

  if (mode === "summary") {
    return (
      <>
        <GroupWhatsAppSummary
          groupId={groupId}
          links={links}
          hasError={Boolean(linksError)}
          canManage={canManage}
          onManage={() => setIsManaging(true)}
        />

        {isManaging && (
          <ManageBroadcastsDialog
            groupId={groupId}
            initialBroadcasts={links?.broadcasts ?? []}
            onClose={() => setIsManaging(false)}
          />
        )}
      </>
    );
  }

  return (
    <>
      <Card>
        <CardContent className="space-y-5 p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700">
                <MessageCircle className="h-5 w-5" aria-hidden="true" />
              </span>
              <div>
                <h2 className="text-base font-semibold text-slate-900">
                  WhatsApp broadcast tracking
                </h2>
                <p className="mt-1 text-sm leading-6 text-slate-600">
                  Each recipient is identified when any selected spreadsheet field
                  matches a submitted value. If a value is ambiguous, it stays in
                  Needs review instead of being guessed.
                </p>
              </div>
            </div>
            {canManage && (
              <Button
                type="button"
                variant={hasLinkedBroadcasts ? "secondary" : "primary"}
                size="sm"
                onClick={() => setIsManaging(true)}
              >
                <Link2 className="h-4 w-4" aria-hidden="true" />
                {hasLinkedBroadcasts ? "Manage broadcasts" : "Link broadcasts"}
              </Button>
            )}
          </div>

          {linksError ? (
            <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              Linked WhatsApp broadcasts could not be loaded.
            </div>
          ) : !hasLinkedBroadcasts ? (
            <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-5 py-8 text-center">
              <div className="font-medium text-slate-800">No WhatsApp broadcasts linked</div>
              <p className="mt-1 text-sm text-slate-500">
                Link one or more existing broadcasts to see who has or has not submitted.
              </p>
            </div>
          ) : (
            <>
              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Linked broadcasts
                </div>
                <div className="flex flex-wrap gap-2">
                  {links?.broadcasts.map((broadcast) => (
                    <span
                      key={broadcast.id}
                      className="inline-flex max-w-full items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-sm text-emerald-900"
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{broadcast.name}</span>
                        <span className="block truncate text-[11px] text-emerald-700">
                          {broadcastMatchingSummary(broadcast)}
                        </span>
                      </span>
                      <span className="text-xs text-emerald-700">
                        {broadcast.recipient_count.toLocaleString()}
                      </span>
                    </span>
                  ))}
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <TrackingStat
                  label="Broadcast recipients"
                  value={totalRecipientCount}
                  icon={<Users className="h-4 w-4" aria-hidden="true" />}
                />
                <TrackingStat
                  label="Identified"
                  value={submittedRecipientCount}
                  detail={matchesQuery.data && submissionRate !== null
                    ? `${submissionRate}% of recipients · ${matchesQuery.data.counts.matched_submission_count.toLocaleString()} uploads`
                    : undefined}
                  tone="success"
                  icon={<CheckCircle2 className="h-4 w-4" aria-hidden="true" />}
                />
                <TrackingStat
                  label="Not submitted"
                  value={matchesQuery.data?.counts.not_submitted_count ?? null}
                  tone="warning"
                  icon={<AlertCircle className="h-4 w-4" aria-hidden="true" />}
                />
                <TrackingStat
                  label="Needs review"
                  value={matchesQuery.data?.counts.needs_review_count ?? null}
                  detail={matchesQuery.data
                    ? `${matchesQuery.data.counts.needs_review_submission_count.toLocaleString()} possible uploads`
                    : undefined}
                  tone="warning"
                  icon={<AlertCircle className="h-4 w-4" aria-hidden="true" />}
                />
                <TrackingStat
                  label="Duplicate uploads"
                  value={matchesQuery.data?.counts.multiple_submission_count ?? null}
                  detail="Recipients with repeated passenger passport details"
                  tone="info"
                  icon={<MessageCircle className="h-4 w-4" aria-hidden="true" />}
                />
                <TrackingStat
                  label="Unidentified uploads"
                  value={matchesQuery.data?.counts.unmatched_submission_count ?? null}
                  detail="Not linked to a broadcast recipient"
                  tone="danger"
                  icon={<AlertCircle className="h-4 w-4" aria-hidden="true" />}
                />
                <TrackingStat
                  label="Replaced"
                  value={matchesQuery.data?.counts.replacement_count ?? null}
                  detail="Original recipients stopped from future messages"
                  tone="info"
                  icon={<UserRoundCheck className="h-4 w-4" aria-hidden="true" />}
                />
                <TrackingStat
                  label="Removed uploads"
                  value={matchesQuery.data?.counts.rejected_upload_count ?? null}
                  detail="Kept safely and available to add back"
                  tone="default"
                  icon={<UserRoundX className="h-4 w-4" aria-hidden="true" />}
                />
              </div>

              <div className="space-y-3">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <div
                    className="flex flex-wrap gap-2"
                    aria-label="Filter broadcast recipients by submission status"
                  >
                    {MATCH_FILTERS.map((filter) => (
                      <div
                        key={filter.value}
                        className="group/filter relative"
                      >
                        <button
                          type="button"
                          aria-pressed={matchFilter === filter.value}
                          aria-describedby={
                            filter.description
                              ? `match-filter-help-${filter.value}`
                              : undefined
                          }
                          onClick={() => {
                            setMatchFilter(filter.value);
                            setMatchPage(1);
                          }}
                          className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
                            matchFilter === filter.value
                              ? "border-blue-600 bg-blue-600 text-white"
                              : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                          }`}
                        >
                          {filter.label}
                          {filter.description && (
                            <CircleHelp
                              className="h-3.5 w-3.5"
                              aria-hidden="true"
                            />
                          )}
                        </button>
                        {filter.description && (
                          <span
                            id={`match-filter-help-${filter.value}`}
                            role="tooltip"
                            className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 hidden w-64 -translate-x-1/2 rounded-lg bg-slate-900 px-3 py-2 text-left text-xs font-medium leading-5 text-white shadow-lg group-hover/filter:block group-focus-within/filter:block"
                          >
                            {filter.description}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    {(links?.broadcasts.length ?? 0) > 1 && (
                      <>
                        <label
                          htmlFor="whatsapp-broadcast-filter"
                          className="text-xs font-semibold text-slate-600"
                        >
                          Broadcast
                        </label>
                        <select
                          id="whatsapp-broadcast-filter"
                          value={broadcastFilter}
                          onChange={(event) => {
                            setBroadcastFilter(event.target.value);
                            setMatchPage(1);
                          }}
                          className="h-9 max-w-72 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                        >
                          <option value="all">All linked broadcasts</option>
                          {links?.broadcasts.map((broadcast) => (
                            <option key={broadcast.id} value={broadcast.id}>
                              {broadcast.name}
                            </option>
                          ))}
                        </select>
                      </>
                    )}
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      disabled={
                        exportTracking.isPending
                        || matchesQuery.isLoading
                        || !matchesQuery.data?.total
                      }
                      aria-label={`Export ${
                        MATCH_FILTERS.find(
                          (filter) => filter.value === matchFilter,
                        )?.label ?? "current tracking view"
                      } to Excel`}
                      onClick={() => {
                        exportTracking.reset();
                        exportTracking.mutate({
                          groupId,
                          status: matchFilter,
                          broadcastId: broadcastFilter === "all"
                            ? undefined
                            : broadcastFilter,
                        });
                      }}
                    >
                      {exportTracking.isPending ? (
                        <Loader2
                          className="h-4 w-4 animate-spin"
                          aria-hidden="true"
                        />
                      ) : (
                        <Download className="h-4 w-4" aria-hidden="true" />
                      )}
                      {exportTracking.isPending ? "Exporting" : "Export Excel"}
                    </Button>
                  </div>
                </div>

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
            </>
          )}
        </CardContent>
      </Card>

      {isManaging && (
        <ManageBroadcastsDialog
          groupId={groupId}
          initialBroadcasts={links?.broadcasts ?? []}
          onClose={() => setIsManaging(false)}
        />
      )}
      {replacementRow && (
        <ReplacementDialog
          groupId={groupId}
          row={replacementRow}
          onClose={() => setReplacementRow(null)}
          onResolved={() => {
            setReplacementRow(null);
            setMatchFilter("replacement");
            setMatchPage(1);
          }}
        />
      )}
      <ConfirmDialog
        isOpen={Boolean(rejectRow)}
        title="Reject and remove this unidentified upload?"
        description={`${
          rejectRow ? rowPrimaryName(rejectRow) : "This upload"
        } will move to Removed uploads. Nothing is deleted, and you can add the upload back later.`}
        confirmLabel="Reject/remove upload"
        variant="danger"
        isLoading={rejectUpload.isPending}
        onClose={() => {
          setRejectRow(null);
          setRejectRequestId(null);
        }}
        onConfirm={() => {
          const submissionId = rejectRow?.submission_ids[0];
          if (!submissionId) {
            setRejectRow(null);
            setRejectRequestId(null);
            setResolutionError("This upload could not be selected. Refresh and try again.");
            return;
          }
          setResolutionError(null);
          rejectUpload.mutate(
            {
              submissionId,
              requestId: rejectRequestId ?? createRosterRequestId(),
            },
            {
              onSuccess: () => {
                setRejectRow(null);
                setRejectRequestId(null);
                setMatchFilter("rejected_upload");
                setMatchPage(1);
              },
              onError: () => {
                setRejectRow(null);
                setRejectRequestId(null);
                setResolutionError(
                  "The unidentified upload could not be removed. Refresh and try again.",
                );
              },
            },
          );
        }}
      />
      <ConfirmDialog
        isOpen={Boolean(restoreRow)}
        title={
          restoreRow?.status === "replacement"
            ? "Restore the original recipient?"
            : "Add this upload back?"
        }
        description={
          restoreRow?.status === "replacement"
            ? "The original WhatsApp recipient will become active for future messages again, and this replacement upload will return to Unidentified uploads."
            : "This upload will return to Unidentified uploads so you can review or assign it again."
        }
        confirmLabel={
          restoreRow?.status === "replacement"
            ? "Restore original recipient"
            : "Add upload back"
        }
        isLoading={restoreResolution.isPending}
        onClose={() => setRestoreRow(null)}
        onConfirm={() => {
          const resolutionId = restoreRow?.resolution_id;
          if (!resolutionId) {
            setRestoreRow(null);
            setResolutionError("This record could not be restored. Refresh and try again.");
            return;
          }
          setResolutionError(null);
          restoreResolution.mutate(resolutionId, {
            onSuccess: () => {
              setRestoreRow(null);
              setMatchFilter("unmatched_submission");
              setMatchPage(1);
            },
            onError: () => {
              setRestoreRow(null);
              setResolutionError(
                "This record could not be restored. Refresh and try again.",
              );
            },
          });
        }}
      />
    </>
  );
}
