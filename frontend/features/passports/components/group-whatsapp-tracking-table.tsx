"use client";

import { Loader2, RotateCcw, UserRoundCheck, UserRoundX } from "lucide-react";
import Link from "next/link";
import { Badge, Button } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { formatDateTime } from "@/lib/utils/format";
import type { GroupWhatsAppMatch, GroupWhatsAppMatchStatus, GroupWhatsAppSubmissionDetail } from "../api/upload-links.api";
import { groupWhatsAppEvidenceLabel } from "./whatsapp-match-evidence";
import { matchExplanation } from "./whatsapp-match-description";
import { MATCH_FILTERS, type MatchFilter, firstDisplayValue, fieldLabel, uniqueEvidenceKinds, uniqueImportedDetails, submissionDetailEntries, submissionPrimaryPhone } from "./group-whatsapp-tracking-model";

export function TrackingStat({
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
                          {groupWhatsAppEvidenceLabel(kind, row)}
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
                                  )
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
                                {row.duplicate_submission_ids?.includes(submissionId) && (
                                  <span className="ml-1 rounded bg-amber-50 px-1 text-amber-800">Duplicate</span>
                                )}
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

export function MatchStatusBadge({ status }: { status: GroupWhatsAppMatchStatus }) {
  if (status === "multiple_submissions") {
    return <Badge variant="warning">Duplicate uploads</Badge>;
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

export function SubmissionDetailsList({
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
