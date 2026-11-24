import { RotateCcw, UserRoundCheck, UserRoundX } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { formatDateTime } from "@/lib/utils/format";
import { groupWhatsAppEvidenceLabel } from "./whatsapp-match-evidence";
import { matchExplanation } from "./whatsapp-match-description";
import {
  firstDisplayValue,
  fieldLabel,
  uniqueEvidenceKinds,
  uniqueImportedDetails,
  submissionPrimaryPhone,
} from "./group-whatsapp-tracking-model";
import { MatchStatusBadge, SubmissionDetailsList } from "./group-whatsapp-tracking-presentation";
import type { GroupWhatsAppMatch } from "../api/upload-links.api";

export interface MatchRowActions {
  canManage: boolean;
  isActionPending: boolean;
  onMarkReplacement: (row: GroupWhatsAppMatch) => void;
  onReject: (row: GroupWhatsAppMatch) => void;
  onRestore: (row: GroupWhatsAppMatch) => void;
}

export function groupWhatsAppMatchKey(row: GroupWhatsAppMatch, index: number) {
  return row.resolution_id
    ?? `${row.normalized_phone ?? "record"}-${row.recipient_ids[0] ?? row.submission_ids[0] ?? index}`;
}

type Props = MatchRowActions & { row: GroupWhatsAppMatch };

export function BroadcastMatchRow({
  row,
  canManage,
  isActionPending,
  onMarkReplacement,
  onReject,
  onRestore,
}: Props) {
  const importedDetails = uniqueImportedDetails(row);
  const linkedSubmissionIds = row.status === "needs_review"
    ? row.candidate_submission_ids
    : row.submission_ids;
  const isUnidentifiedUpload = row.status === "unmatched_submission";
  const isSubmissionLedRow = (isUnidentifiedUpload
    || row.status === "replacement"
    || row.status === "rejected_upload");
  return (
    <tr
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
}
