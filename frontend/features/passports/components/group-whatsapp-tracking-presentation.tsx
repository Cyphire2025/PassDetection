import { Badge } from "@/components/ui";
import type { GroupWhatsAppMatchStatus, GroupWhatsAppSubmissionDetail } from "../api/upload-links.api";
import { fieldLabel, submissionDetailEntries } from "./group-whatsapp-tracking-model";

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
