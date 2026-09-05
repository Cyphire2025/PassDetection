"use client";

import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Download,
  Link2,
  Loader2,
  MessageCircle,
  RotateCcw,
  Search,
  UserRoundCheck,
  UserRoundX,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import {
  WorkspacePageHeader,
} from "@/components/shared/workspace-ui";
import {
  Badge,
  Button,
  buttonVariants,
  Card,
  CardContent,
  ConfirmDialog,
  Input,
  Skeleton,
} from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { cn } from "@/lib/utils/cn";
import { formatDateTime } from "@/lib/utils/format";
import { canAccessWhatsAppBroadcasts } from "@/lib/utils/role-access";
import {
  selectHasHydrated,
  selectUserRole,
  useAuthStore,
} from "@/stores/auth.store";
import type {
  GroupWhatsAppMatch,
  GroupWhatsAppMatchStatus,
  GroupWhatsAppSubmissionDetail,
  ReplacementCandidate,
} from "../api/upload-links.api";
import {
  useExportWhatsAppTracking,
} from "../hooks/use-passports";
import {
  useGroupWhatsAppLinks,
  useGroupWhatsAppMatches,
  useRejectUnidentifiedUpload,
  useReplacementCandidates,
  useResolveUnidentifiedReplacement,
  useRestoreRosterResolution,
  useUpdateGroupWhatsAppLinks,
} from "../hooks/use-upload-links";
import { WhatsAppBroadcastSelector } from "./whatsapp-broadcast-selector";

type MatchFilter = "all" | GroupWhatsAppMatchStatus;

const MATCH_FILTERS: Array<{
  value: MatchFilter;
  label: string;
  description?: string;
}> = [
  { value: "all", label: "All records" },
  { value: "submitted", label: "Identified" },
  { value: "not_submitted", label: "Not submitted" },
  { value: "multiple_submissions", label: "Multiple submissions" },
  { value: "needs_review", label: "Needs review" },
  {
    value: "unmatched_submission",
    label: "Unidentified uploads",
    description:
      "People who uploaded their details but are not in the linked WhatsApp broadcast lists.",
  },
  {
    value: "replacement",
    label: "Replaced",
    description:
      "People added as replacements, together with the original broadcast recipients they replaced.",
  },
  {
    value: "rejected_upload",
    label: "Removed uploads",
    description:
      "Unidentified uploads removed from the active list. They can be added back at any time.",
  },
];

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
        : ROUTES.dashboard.passports) as never,
    );
  }, [canAccessWhatsApp, hasHydrated, role, router]);

  if (!hasHydrated || !canAccessWhatsApp) return null;

  return (
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
    return <Skeleton className="h-44 w-full rounded-2xl" />;
  }

  if (mode === "summary") {
    return (
      <>
        <Card>
          <CardContent className="space-y-4 p-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700">
                  <MessageCircle className="h-5 w-5" aria-hidden="true" />
                </span>
                <div>
                  <h2 className="text-base font-semibold text-slate-900">
                    WhatsApp broadcasts
                  </h2>
                  <p className="mt-1 text-sm text-slate-600">
                    Link recipient lists and open tracking when you need the full comparison.
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
              <div
                role="alert"
                className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
              >
                Linked WhatsApp broadcasts could not be loaded.
              </div>
            ) : !hasLinkedBroadcasts ? (
              <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-5 py-7 text-center">
                <div className="font-medium text-slate-800">
                  No WhatsApp broadcasts linked
                </div>
                <p className="mt-1 text-sm text-slate-500">
                  Link one or more existing broadcasts to track submissions.
                </p>
              </div>
            ) : (
              <div className="flex flex-col gap-4 rounded-xl border border-emerald-200 bg-emerald-50/50 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex min-w-0 flex-wrap gap-2">
                  {links?.broadcasts.map((broadcast) => (
                    <span
                      key={broadcast.id}
                      className="rounded-full border border-emerald-200 bg-white px-3 py-1.5 text-sm font-semibold text-emerald-900"
                    >
                      {broadcast.name}
                    </span>
                  ))}
                </div>
                <Link
                  href={
                    ROUTES.dashboard.passportGroupWhatsAppTracking(groupId) as never
                  }
                  className={cn(
                    buttonVariants({ size: "sm" }),
                    "shrink-0",
                  )}
                >
                  View tracking
                  <ChevronRight className="h-4 w-4" aria-hidden="true" />
                </Link>
              </div>
            )}
          </CardContent>
        </Card>

        {isManaging && (
          <ManageBroadcastsDialog
            groupId={groupId}
            initialIds={
              links?.broadcasts.map((broadcast) => broadcast.id) ?? []
            }
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
                  Imported phone numbers, emails, passport numbers, staff codes,
                  names entered in the form, and names read from passports are
                  compared together. Uncertain matches are kept for review
                  instead of being guessed.
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
                      className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-sm text-emerald-900"
                    >
                      <span className="font-medium">{broadcast.name}</span>
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
                  label="Multiple uploads"
                  value={matchesQuery.data?.counts.multiple_submission_count ?? null}
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

                {exportTracking.error && (
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
          initialIds={links?.broadcasts.map((broadcast) => broadcast.id) ?? []}
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

function ReplacementDialog({
  groupId,
  row,
  onClose,
  onResolved,
}: {
  groupId: string;
  row: GroupWhatsAppMatch;
  onClose: () => void;
  onResolved: () => void;
}) {
  const titleId = useId();
  const [search, setSearch] = useState("");
  const [requestId] = useState(createRosterRequestId);
  const [selectedRecipientId, setSelectedRecipientId] = useState<string | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const candidatesQuery = useReplacementCandidates(groupId);
  const resolveReplacement = useResolveUnidentifiedReplacement(groupId);
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const candidates = (candidatesQuery.data?.items ?? []).filter((candidate) => (
    !normalizedSearch || replacementCandidateSearchText(candidate).includes(
      normalizedSearch,
    )
  ));
  const selectedCandidate = candidatesQuery.data?.items.find(
    (candidate) => candidate.recipient_id === selectedRecipientId,
  );

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !resolveReplacement.isPending) onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose, resolveReplacement.isPending]);

  const confirmReplacement = () => {
    const submissionId = row.submission_ids[0];
    if (!submissionId || !selectedRecipientId) return;
    setError(null);
    resolveReplacement.mutate(
      {
        submissionId,
        recipientId: selectedRecipientId,
        requestId,
      },
      {
        onSuccess: onResolved,
        onError: () => setError(
          "The replacement could not be saved. The recipient may have changed; refresh and try again.",
        ),
      },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-busy={resolveReplacement.isPending}
        className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4 sm:px-6">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-slate-900">
              Mark as a replacement
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              Choose the person from the current WhatsApp broadcast who is no
              longer going. Future messages to that original recipient will stop.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close replacement dialog"
            onClick={onClose}
            disabled={resolveReplacement.isPending}
            className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5 sm:p-6">
          <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">
              New person going
            </div>
            <div className="mt-1 font-semibold text-slate-900">
              {rowPrimaryName(row)}
            </div>
            <div className="mt-1 text-sm text-slate-600">
              {submissionPrimaryPhone(row) || "No submitted phone number"}
            </div>
            <SubmissionDetailsList
              details={row.submission_details}
              className="mt-3"
            />
          </div>

          <div className="space-y-3">
            <Input
              label="Find the original recipient"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search name, phone number, broadcast, or imported detail"
              leftAddon={<Search className="h-4 w-4" aria-hidden="true" />}
              autoFocus
              disabled={resolveReplacement.isPending}
            />

            {candidatesQuery.isLoading ? (
              <div className="flex items-center justify-center gap-2 rounded-xl border border-slate-200 py-10 text-sm text-slate-500">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Loading current broadcast recipients
              </div>
            ) : candidatesQuery.error ? (
              <div
                role="alert"
                className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
              >
                Current recipients could not be loaded. Close this box and try
                again.
              </div>
            ) : candidates.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center">
                <div className="font-medium text-slate-700">
                  {normalizedSearch
                    ? "No recipient matches this search"
                    : "No active recipient is available to replace"}
                </div>
                <p className="mt-1 text-sm text-slate-500">
                  {normalizedSearch
                    ? "Try a name, phone number, or broadcast name."
                    : "Every linked recipient may already be inactive or replaced."}
                </p>
              </div>
            ) : (
              <div
                role="radiogroup"
                aria-label="Choose the original broadcast recipient"
                className="space-y-2"
              >
                {candidates.map((candidate) => {
                  const isSelected = (
                    candidate.recipient_id === selectedRecipientId
                  );
                  const details = Object.entries(candidate.imported_fields)
                    .filter(([, value]) => value.trim());
                  return (
                    <div
                      key={candidate.recipient_id}
                      className={`overflow-hidden rounded-xl border transition ${
                        isSelected
                          ? "border-blue-500 bg-blue-50 ring-2 ring-blue-100"
                          : "border-slate-200 bg-white hover:border-slate-300"
                      }`}
                    >
                      <button
                        type="button"
                        role="radio"
                        aria-checked={isSelected}
                        disabled={resolveReplacement.isPending}
                        onClick={() => {
                          setSelectedRecipientId(candidate.recipient_id);
                          setError(null);
                        }}
                        className="flex w-full items-start gap-3 p-4 text-left disabled:opacity-60"
                      >
                        <span
                          className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${
                            isSelected
                              ? "border-blue-600 bg-blue-600 text-white"
                              : "border-slate-300 bg-white"
                          }`}
                        >
                          {isSelected && (
                            <CheckCircle2
                              className="h-3.5 w-3.5"
                              aria-hidden="true"
                            />
                          )}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block font-semibold text-slate-900">
                            {candidate.name?.trim() || "Unnamed recipient"}
                          </span>
                          <span className="mt-0.5 block text-sm text-slate-600">
                            {candidate.phone}
                          </span>
                          <span className="mt-2 flex flex-wrap gap-1.5">
                            {candidate.broadcast_names.map((name) => (
                              <span
                                key={name}
                                className="rounded-full bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-800"
                              >
                                {name}
                              </span>
                            ))}
                          </span>
                        </span>
                      </button>
                      {details.length > 0 && (
                        <details className="border-t border-slate-100 px-4 py-3">
                          <summary className="cursor-pointer text-xs font-semibold text-blue-700">
                            View imported details
                          </summary>
                          <dl className="mt-3 grid gap-2 sm:grid-cols-2">
                            {details.map(([key, value]) => (
                              <div key={key} className="min-w-0">
                                <dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                                  {fieldLabel(key)}
                                </dt>
                                <dd className="break-words text-xs text-slate-700">
                                  {value}
                                </dd>
                              </div>
                            ))}
                          </dl>
                        </details>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {selectedCandidate && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900">
              <strong>{selectedCandidate.name || selectedCandidate.phone}</strong>{" "}
              will be recorded as the original person who opted out. The new
              upload will remain active as their replacement.
            </div>
          )}
          {error && (
            <div
              role="alert"
              className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            >
              {error}
            </div>
          )}
        </div>

        <div className="flex flex-wrap justify-end gap-3 border-t border-slate-200 px-5 py-4 sm:px-6">
          <Button
            type="button"
            variant="secondary"
            onClick={onClose}
            disabled={resolveReplacement.isPending}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={confirmReplacement}
            isLoading={resolveReplacement.isPending}
            disabled={
              !selectedRecipientId
              || !row.submission_ids[0]
              || candidatesQuery.isLoading
              || Boolean(candidatesQuery.error)
            }
          >
            Confirm replacement
          </Button>
        </div>
      </div>
    </div>
  );
}

function ManageBroadcastsDialog({
  groupId,
  initialIds,
  onClose,
}: {
  groupId: string;
  initialIds: string[];
  onClose: () => void;
}) {
  const titleId = useId();
  const [selectedIds, setSelectedIds] = useState<string[]>(() => [...initialIds]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmUnlinkAll, setConfirmUnlinkAll] = useState(false);
  const updateLinks = useUpdateGroupWhatsAppLinks(groupId);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !updateLinks.isPending) onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose, updateLinks.isPending]);

  const saveLinks = () => {
    setSaveError(null);
    updateLinks.mutate(selectedIds, {
      onSuccess: onClose,
      onError: () => setSaveError(
        "The WhatsApp broadcasts could not be linked. Try again.",
      ),
    });
  };

  return (
    <>
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm">
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          aria-busy={updateLinks.isPending}
          className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        >
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4 sm:px-6">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-slate-900">
              Link WhatsApp broadcasts
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              Select every broadcast whose recipients should be compared with this passport group.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close WhatsApp broadcast linking dialog"
            onClick={onClose}
            disabled={updateLinks.isPending}
            className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div className="overflow-y-auto p-4 sm:p-6">
          <WhatsAppBroadcastSelector
            selectedIds={selectedIds}
            onChange={setSelectedIds}
            disabled={updateLinks.isPending}
            groupId={groupId}
          />
          {saveError && (
            <div role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {saveError}
            </div>
          )}
        </div>

          <div className="flex flex-wrap justify-end gap-3 border-t border-slate-200 px-5 py-4 sm:px-6">
            <Button type="button" variant="secondary" onClick={onClose} disabled={updateLinks.isPending}>
              Cancel
            </Button>
            <Button
              type="button"
              isLoading={updateLinks.isPending}
              disabled={updateLinks.isPending}
              onClick={() => {
                if (initialIds.length > 0 && selectedIds.length === 0) {
                  setConfirmUnlinkAll(true);
                  return;
                }
                saveLinks();
              }}
            >
              Save linked broadcasts
            </Button>
          </div>
        </div>
      </div>
      <ConfirmDialog
        isOpen={confirmUnlinkAll}
        title="Unlink every WhatsApp broadcast?"
        description="Recipient submission tracking will be removed from this group until a broadcast is linked again. The broadcasts and passport submissions will not be deleted."
        confirmLabel="Unlink all broadcasts"
        variant="danger"
        isLoading={updateLinks.isPending}
        onClose={() => setConfirmUnlinkAll(false)}
        onConfirm={() => {
          setConfirmUnlinkAll(false);
          saveLinks();
        }}
      />
    </>
  );
}

function TrackingStat({
  label,
  value,
  tone = "default",
  icon,
  detail,
}: {
  label: string;
  value: number | null;
  tone?: "default" | "success" | "warning" | "info" | "danger";
  icon: React.ReactNode;
  detail?: string;
}) {
  const classes = {
    default: "border-slate-200 bg-slate-50 text-slate-700",
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
    warning: "border-amber-200 bg-amber-50 text-amber-800",
    info: "border-blue-200 bg-blue-50 text-blue-800",
    danger: "border-red-200 bg-red-50 text-red-800",
  }[tone];
  return (
    <div className={`rounded-xl border p-4 ${classes}`}>
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide">
        {icon}
        {label}
      </div>
      <div
        className="mt-2 text-2xl font-bold"
        aria-label={value === null ? `${label} unavailable` : undefined}
      >
        {value === null ? "—" : value.toLocaleString()}
      </div>
      {detail && <div className="mt-1 text-xs font-medium">{detail}</div>}
    </div>
  );
}

function BroadcastMatchTable({
  rows,
  isLoading,
  error,
  filter,
  canManage,
  isActionPending,
  onMarkReplacement,
  onReject,
  onRestore,
}: {
  rows: GroupWhatsAppMatch[];
  isLoading: boolean;
  error: unknown;
  filter: MatchFilter;
  canManage: boolean;
  isActionPending: boolean;
  onMarkReplacement: (row: GroupWhatsAppMatch) => void;
  onReject: (row: GroupWhatsAppMatch) => void;
  onRestore: (row: GroupWhatsAppMatch) => void;
}) {
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
          {rows.map((row, index) => {
            const importedDetails = uniqueImportedDetails(row);
            const linkedSubmissionIds = row.status === "needs_review"
              ? row.candidate_submission_ids
              : row.submission_ids;
            const isUnidentifiedUpload = row.status === "unmatched_submission";
            const isSubmissionLedRow = (
              isUnidentifiedUpload
              || row.status === "replacement"
              || row.status === "rejected_upload"
            );
            return (
              <tr
                key={
                  row.resolution_id
                  ?? `${row.normalized_phone ?? "record"}-${row.recipient_ids[0] ?? row.submission_ids[0] ?? index}`
                }
                className="align-top"
              >
                <td className="px-4 py-3">
                  <div className="font-semibold text-slate-900">
                    {firstDisplayValue(
                      isSubmissionLedRow
                        ? row.submission_names
                        : row.recipient_names,
                    ) || (
                      isSubmissionLedRow
                        ? "Unidentified submission"
                        : "Unnamed recipient"
                    )}
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    {(isSubmissionLedRow
                      ? submissionPrimaryPhone(row)
                      : row.normalized_phone) || (
                      isSubmissionLedRow
                        ? "No submitted phone number"
                        : "No usable WhatsApp number"
                    )}
                  </div>
                  {isSubmissionLedRow && (
                    <SubmissionDetailsList
                      details={row.submission_details}
                      className="mt-2"
                    />
                  )}
                </td>
                <td className="px-4 py-3">
                  {row.status === "replacement" && (
                    <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
                      <div className="text-[10px] font-semibold uppercase tracking-wide text-amber-700">
                        Original person replaced
                      </div>
                      <div className="mt-1 text-xs font-semibold text-slate-800">
                        {firstDisplayValue(row.recipient_names)
                          || "Unnamed recipient"}
                      </div>
                      <div className="mt-0.5 text-xs text-slate-600">
                        {row.normalized_phone || "No usable WhatsApp number"}
                      </div>
                    </div>
                  )}
                  {importedDetails.length > 0 ? (
                    <details>
                      <summary className="cursor-pointer text-xs font-semibold text-blue-700">
                        View {importedDetails.length} imported detail
                        {importedDetails.length === 1 ? "" : "s"}
                      </summary>
                      <dl className="mt-2 grid max-w-sm gap-2 rounded-lg bg-slate-50 p-3">
                        {importedDetails.map(([key, value]) => (
                          <div key={`${key}:${value}`} className="min-w-0">
                            <dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                              {fieldLabel(key)}
                            </dt>
                            <dd className="break-words text-xs text-slate-700">
                              {value}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    </details>
                  ) : (
                    <span className="text-xs text-slate-400">
                      {row.status === "replacement"
                        ? "No extra imported details"
                        : isSubmissionLedRow
                        ? "Not a broadcast recipient"
                        : "No extra fields"}
                    </span>
                  )}
                </td>
                <td className="px-4 py-3">
                  {row.broadcast_names.length > 0 ? (
                    <div className="flex max-w-sm flex-wrap gap-1.5">
                      {row.broadcast_names.map((name, broadcastIndex) => (
                        <span
                          key={`${row.broadcast_ids[broadcastIndex] ?? name}-${broadcastIndex}`}
                          className="rounded-full bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-800"
                        >
                          {name}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span className="text-xs text-slate-400">
                      No linked broadcast
                    </span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <MatchStatusBadge status={row.status} />
                  <div className="mt-2 max-w-xs text-xs leading-5 text-slate-500">
                    {matchExplanation(row)}
                  </div>
                  {row.match_evidence.length > 0 && (
                    <div className="mt-2 flex max-w-xs flex-wrap gap-1">
                      {uniqueEvidenceKinds(row).map((kind) => (
                        <span
                          key={kind}
                          className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600"
                        >
                          {evidenceLabel(kind)}
                        </span>
                      ))}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3">
                  {row.submission_names.length > 0 ? (
                    <div>
                      <div className="font-medium text-slate-800">
                        {row.submission_names.join(", ")}
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        {linkedSubmissionIds.length}{" "}
                        {row.status === "needs_review"
                          ? "candidate"
                          : "submission"}
                        {linkedSubmissionIds.length === 1 ? "" : "s"}
                      </div>
                      {linkedSubmissionIds.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-2">
                          {linkedSubmissionIds.map(
                            (submissionId, submissionIndex) => (
                              <Link
                                key={submissionId}
                                href={
                                  ROUTES.dashboard.passportDetail(
                                    submissionId,
                                  ) as never
                                }
                                className="text-xs font-semibold text-blue-700 hover:text-blue-800 hover:underline"
                              >
                                Open{" "}
                                {row.status === "needs_review"
                                  ? "candidate"
                                  : "submission"}
                                {linkedSubmissionIds.length > 1
                                  ? ` ${submissionIndex + 1}`
                                  : ""}
                              </Link>
                            ),
                          )}
                        </div>
                      )}
                    </div>
                  ) : (
                    <span className="text-slate-400">None</span>
                  )}
                </td>
                <td className="px-4 py-3 text-slate-500">
                  {row.updated_at ? formatDateTime(row.updated_at) : "—"}
                </td>
                {canManage && (
                  <td className="px-4 py-3">
                    {row.status === "unmatched_submission" ? (
                      <div className="flex min-w-40 flex-col items-start gap-2">
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          disabled={isActionPending || !row.submission_ids[0]}
                          onClick={() => onMarkReplacement(row)}
                        >
                          <UserRoundCheck
                            className="h-4 w-4"
                            aria-hidden="true"
                          />
                          Mark as replacement
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="text-red-700 hover:bg-red-50 hover:text-red-800"
                          disabled={isActionPending || !row.submission_ids[0]}
                          onClick={() => onReject(row)}
                        >
                          <UserRoundX
                            className="h-4 w-4"
                            aria-hidden="true"
                          />
                          Reject/remove
                        </Button>
                      </div>
                    ) : (
                      (
                        row.status === "replacement"
                        || row.status === "rejected_upload"
                      ) && (
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          disabled={isActionPending || !row.resolution_id}
                          onClick={() => onRestore(row)}
                        >
                          <RotateCcw
                            className="h-4 w-4"
                            aria-hidden="true"
                          />
                          {row.status === "replacement"
                            ? "Restore original person"
                            : "Add upload back"}
                        </Button>
                      )
                    )}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function MatchStatusBadge({ status }: { status: GroupWhatsAppMatchStatus }) {
  if (status === "multiple_submissions") {
    return <Badge variant="warning">Multiple submissions</Badge>;
  }
  if (status === "submitted") {
    return <Badge variant="success">Identified</Badge>;
  }
  if (status === "needs_review") {
    return <Badge variant="warning">Needs review</Badge>;
  }
  if (status === "unmatched_submission") {
    return <Badge variant="destructive">Unidentified upload</Badge>;
  }
  if (status === "replacement") {
    return <Badge variant="secondary">Replacement</Badge>;
  }
  if (status === "rejected_upload") {
    return <Badge variant="secondary">Removed upload</Badge>;
  }
  return <Badge variant="secondary">Not submitted</Badge>;
}

function firstDisplayValue(values: string[]) {
  return values.find((value) => value.trim()) ?? "";
}

function fieldLabel(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function evidenceLabel(
  value: GroupWhatsAppMatch["match_evidence"][number]["kind"],
): string {
  const labels = {
    phone: "Phone number",
    email: "Email",
    passport_number: "Passport number",
    staff_code: "Staff code",
    entered_name: "Name entered in form",
    passport_name: "Name read from passport",
  };
  return labels[value];
}

function uniqueEvidenceKinds(
  row: GroupWhatsAppMatch,
): GroupWhatsAppMatch["match_evidence"][number]["kind"][] {
  return Array.from(new Set(row.match_evidence.map((item) => item.kind)));
}

function uniqueImportedDetails(
  row: GroupWhatsAppMatch,
): Array<[string, string]> {
  const unique = new Map<string, [string, string]>();
  for (const recipient of row.recipient_fields) {
    for (const [key, value] of Object.entries(recipient.fields)) {
      const normalizedValue = value.trim();
      if (!normalizedValue) continue;
      unique.set(
        `${key.toLowerCase()}:${normalizedValue.toLowerCase()}`,
        [key, normalizedValue],
      );
    }
  }
  return Array.from(unique.values()).sort(([left], [right]) =>
    fieldLabel(left).localeCompare(fieldLabel(right)),
  );
}

function SubmissionDetailsList({
  details,
  className,
}: {
  details: GroupWhatsAppSubmissionDetail[];
  className?: string;
}) {
  if (details.length === 0) return null;
  return (
    <details className={className}>
      <summary className="cursor-pointer text-xs font-semibold text-blue-700">
        View submitted details
      </summary>
      <div className="mt-2 space-y-2">
        {details.map((detail, detailIndex) => (
          <dl
            key={detail.submission_id}
            className="grid max-w-sm gap-2 rounded-lg border border-slate-100 bg-white/80 p-3 sm:grid-cols-2"
          >
            {details.length > 1 && (
              <div className="sm:col-span-2">
                <dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Submission
                </dt>
                <dd className="text-xs font-semibold text-slate-700">
                  {detailIndex + 1}
                </dd>
              </div>
            )}
            {submissionDetailEntries(detail).map(([key, value]) => (
              <div key={`${detail.submission_id}:${key}`} className="min-w-0">
                <dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  {fieldLabel(key)}
                </dt>
                <dd className="break-words text-xs text-slate-700">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        ))}
      </div>
    </details>
  );
}

function submissionDetailEntries(
  detail: GroupWhatsAppSubmissionDetail,
): Array<[string, string]> {
  const entries = new Map<string, [string, string]>();
  const add = (key: string, rawValue: unknown) => {
    const value = displaySubmissionValue(rawValue);
    if (!value) return;
    const normalizedKey = key.trim().toLocaleLowerCase();
    if (!normalizedKey || entries.has(normalizedKey)) return;
    entries.set(normalizedKey, [key, value]);
  };
  add("name", detail.name);
  add("phone", detail.phone);
  add("email", detail.email);
  for (const [key, value] of Object.entries(detail.fields)) add(key, value);
  return Array.from(entries.values());
}

function displaySubmissionValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map(displaySubmissionValue).filter(Boolean).join(", ");
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function rowPrimaryName(row: GroupWhatsAppMatch): string {
  return firstDisplayValue(row.submission_names)
    || firstDisplayValue(row.recipient_names)
    || "This person";
}

function submissionPrimaryPhone(row: GroupWhatsAppMatch): string {
  return row.submission_details.find((detail) => detail.phone?.trim())
    ?.phone?.trim() ?? "";
}

function replacementCandidateSearchText(
  candidate: ReplacementCandidate,
): string {
  return [
    candidate.name,
    candidate.phone,
    ...candidate.broadcast_names,
    ...Object.keys(candidate.imported_fields),
    ...Object.values(candidate.imported_fields),
  ]
    .filter((value): value is string => Boolean(value))
    .join(" ")
    .toLocaleLowerCase();
}

function createRosterRequestId(): string {
  if (
    typeof globalThis.crypto !== "undefined"
    && typeof globalThis.crypto.randomUUID === "function"
  ) {
    return globalThis.crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  if (
    typeof globalThis.crypto !== "undefined"
    && typeof globalThis.crypto.getRandomValues === "function"
  ) {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10).join(""),
  ].join("-");
}

function matchExplanation(row: GroupWhatsAppMatch): string {
  if (row.status === "submitted") {
    return "Automatically linked using reliable matching details.";
  }
  if (row.status === "multiple_submissions") {
    return "Reliable details link this recipient to more than one upload.";
  }
  if (row.status === "needs_review") {
    return "Some details match, but the result is not unique or strong enough to assign automatically.";
  }
  if (row.status === "unmatched_submission") {
    return "This upload could not be linked reliably to anyone in the selected broadcasts.";
  }
  if (row.status === "replacement") {
    return "This person is going in place of the selected original broadcast recipient.";
  }
  if (row.status === "rejected_upload") {
    return "This unidentified upload was removed from the active list without deleting its saved details.";
  }
  return "No submission could be linked reliably to this broadcast recipient.";
}
