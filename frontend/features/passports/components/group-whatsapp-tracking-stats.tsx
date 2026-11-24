import { AlertCircle, CheckCircle2, MessageCircle, UserRoundCheck, UserRoundX, Users } from "lucide-react";
import { TrackingStat } from "./group-whatsapp-tracking-table";
import type { GroupWhatsAppTrackingModel } from "./use-group-whatsapp-tracking";

type Props = Pick<
  GroupWhatsAppTrackingModel,
  | "matchesQuery"
  | "totalRecipientCount"
  | "submittedRecipientCount"
  | "submissionRate"
>;

export function GroupWhatsAppTrackingStats({
  matchesQuery,
  totalRecipientCount,
  submittedRecipientCount,
  submissionRate,
}: Props) {
  return (
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
  );
}
