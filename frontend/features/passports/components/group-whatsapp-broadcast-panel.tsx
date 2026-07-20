"use client";

import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  Link2,
  Loader2,
  MessageCircle,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useState } from "react";
import { PageHeader } from "@/components/shared/page-header";
import {
  Badge,
  Button,
  buttonVariants,
  Card,
  CardContent,
  ConfirmDialog,
  Skeleton,
} from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { cn } from "@/lib/utils/cn";
import { formatDateTime } from "@/lib/utils/format";
import type {
  GroupWhatsAppMatch,
  GroupWhatsAppMatchStatus,
} from "../api/upload-links.api";
import {
  useGroupWhatsAppLinks,
  useGroupWhatsAppMatches,
  useUpdateGroupWhatsAppLinks,
} from "../hooks/use-upload-links";
import { WhatsAppBroadcastSelector } from "./whatsapp-broadcast-selector";

type MatchFilter = "all" | GroupWhatsAppMatchStatus;

const MATCH_FILTERS: Array<{ value: MatchFilter; label: string }> = [
  { value: "all", label: "All records" },
  { value: "submitted", label: "Identified" },
  { value: "not_submitted", label: "Not submitted" },
  { value: "multiple_submissions", label: "Multiple submissions" },
  { value: "needs_review", label: "Needs review" },
  { value: "unmatched_submission", label: "Unidentified uploads" },
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
  return (
    <div className="space-y-6">
      <PageHeader
        title="WhatsApp submission tracking"
        description="Compare linked broadcast recipients with passport submissions."
        actions={(
          <Link
            href={ROUTES.dashboard.passportGroup(groupId) as never}
            className={buttonVariants({ variant: "secondary" })}
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back to group
          </Link>
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
  const matchPageSize = 50;
  const { data: links, isLoading: linksLoading, error: linksError } = (
    useGroupWhatsAppLinks(groupId)
  );
  const hasLinkedBroadcasts = (links?.broadcast_count ?? 0) > 0;
  const canManage = Boolean(links?.can_manage) && !readOnly;
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

              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
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
              </div>

              <div className="space-y-3">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <div
                    className="flex flex-wrap gap-2"
                    aria-label="Filter broadcast recipients by submission status"
                  >
                    {MATCH_FILTERS.map((filter) => (
                      <button
                        key={filter.value}
                        type="button"
                        aria-pressed={matchFilter === filter.value}
                        onClick={() => {
                          setMatchFilter(filter.value);
                          setMatchPage(1);
                        }}
                        className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
                          matchFilter === filter.value
                            ? "border-blue-600 bg-blue-600 text-white"
                            : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                        }`}
                      >
                        {filter.label}
                      </button>
                    ))}
                  </div>
                  {(links?.broadcasts.length ?? 0) > 1 && (
                    <div className="flex shrink-0 items-center gap-2">
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
                    </div>
                  )}
                </div>

                <BroadcastMatchTable
                  rows={matchesQuery.data?.matches ?? []}
                  isLoading={matchesQuery.isLoading || matchesQuery.isFetching}
                  error={matchesQuery.error}
                  filter={matchFilter}
                />
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
    </>
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
}: {
  rows: GroupWhatsAppMatch[];
  isLoading: boolean;
  error: unknown;
  filter: MatchFilter;
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
      <table className="w-full min-w-[1180px] text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-3">Person / upload</th>
            <th className="px-4 py-3">Imported details</th>
            <th className="px-4 py-3">Broadcasts</th>
            <th className="px-4 py-3">Identification</th>
            <th className="px-4 py-3">Submissions</th>
            <th className="px-4 py-3">Updated</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row, index) => {
            const importedDetails = uniqueImportedDetails(row);
            const linkedSubmissionIds = row.status === "needs_review"
              ? row.candidate_submission_ids
              : row.submission_ids;
            const isUnidentifiedUpload = row.status === "unmatched_submission";
            return (
              <tr
                key={`${row.normalized_phone ?? "record"}-${row.recipient_ids[0] ?? row.submission_ids[0] ?? index}`}
                className="align-top"
              >
                <td className="px-4 py-3">
                  <div className="font-semibold text-slate-900">
                    {firstDisplayValue(
                      isUnidentifiedUpload
                        ? row.submission_names
                        : row.recipient_names,
                    ) || (
                      isUnidentifiedUpload
                        ? "Unidentified submission"
                        : "Unnamed recipient"
                    )}
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    {row.normalized_phone || (
                      isUnidentifiedUpload
                        ? "No submitted phone number"
                        : "No usable WhatsApp number"
                    )}
                  </div>
                </td>
                <td className="px-4 py-3">
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
                      {isUnidentifiedUpload
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
  return "No submission could be linked reliably to this broadcast recipient.";
}
