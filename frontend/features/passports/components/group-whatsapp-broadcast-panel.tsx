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
  { value: "all", label: "All people" },
  { value: "submitted", label: "Submitted" },
  { value: "not_submitted", label: "Not submitted" },
  { value: "multiple_submissions", label: "Multiple submissions" },
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
                  Compare people who received the broadcast with passport submissions.
                  The same phone number is counted once even when it appears in several broadcasts.
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
                  label="All recipients"
                  value={totalRecipientCount}
                  icon={<Users className="h-4 w-4" aria-hidden="true" />}
                />
                <TrackingStat
                  label="Submitted"
                  value={submittedRecipientCount}
                  detail={matchesQuery.data && submissionRate !== null
                    ? `${submissionRate}% rate · ${matchesQuery.data.counts.matched_submission_count.toLocaleString()} matched submission records`
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
                  label="Submitted more than once"
                  value={matchesQuery.data?.counts.multiple_submission_count ?? null}
                  tone="info"
                  icon={<MessageCircle className="h-4 w-4" aria-hidden="true" />}
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
  tone?: "default" | "success" | "warning" | "info";
  icon: React.ReactNode;
  detail?: string;
}) {
  const classes = {
    default: "border-slate-200 bg-slate-50 text-slate-700",
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
    warning: "border-amber-200 bg-amber-50 text-amber-800",
    info: "border-blue-200 bg-blue-50 text-blue-800",
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
        No recipients match the “{MATCH_FILTERS.find((item) => item.value === filter)?.label}” filter.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="w-full min-w-[820px] text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-3">Broadcast recipient</th>
            <th className="px-4 py-3">Broadcasts</th>
            <th className="px-4 py-3">Submission status</th>
            <th className="px-4 py-3">Matched submissions</th>
            <th className="px-4 py-3">Updated</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row, index) => (
            <tr
              key={`${row.normalized_phone ?? "recipient"}-${index}`}
              className="align-top"
            >
              <td className="px-4 py-3">
                <div className="font-semibold text-slate-900">
                  {firstDisplayValue(row.recipient_names) || "Unnamed recipient"}
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  {row.normalized_phone || "No comparable phone number"}
                </div>
              </td>
              <td className="px-4 py-3">
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
              </td>
              <td className="px-4 py-3">
                <MatchStatusBadge status={row.status} />
                <div className="mt-1 text-xs text-slate-500">
                  {row.status === "not_submitted"
                    ? "No exact phone match"
                    : "Matched by exact phone number"}
                </div>
              </td>
              <td className="px-4 py-3">
                {row.submission_names.length > 0 ? (
                  <div>
                    <div className="font-medium text-slate-800">
                      {row.submission_names.join(", ")}
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      {row.submission_ids.length} submission
                      {row.submission_ids.length === 1 ? "" : "s"}
                    </div>
                  </div>
                ) : (
                  <span className="text-slate-400">None</span>
                )}
              </td>
              <td className="px-4 py-3 text-slate-500">
                {row.updated_at ? formatDateTime(row.updated_at) : "—"}
              </td>
            </tr>
          ))}
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
    return <Badge variant="success">Submitted</Badge>;
  }
  return <Badge variant="secondary">Not submitted</Badge>;
}

function firstDisplayValue(values: string[]) {
  return values.find((value) => value.trim()) ?? "";
}
