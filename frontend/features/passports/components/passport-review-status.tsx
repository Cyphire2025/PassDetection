"use client";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { PASSPORT_STATUS_COLORS, PASSPORT_STATUS_LABELS } from "@/constants";
import { formatConfidence, formatDateTime } from "@/lib/utils/format";
import { formatPassportDateForUi } from "@/lib/utils/passport-date";
import { getPassportVerificationConfidence } from "../utils/passport-review";
import { getWorkflowStatusMessage } from "./passport-review-model";
import type { ReviewFieldsCardProps } from "./passport-review-types";

export function PassportReviewStatus({ passport, reviewerLabel, approvalFeedback, reviewFields }: Pick<ReviewFieldsCardProps, "passport" | "reviewerLabel" | "approvalFeedback"> & { reviewFields: Record<string, string> }) {
  const workflowStatusMessage = getWorkflowStatusMessage(passport.status);
  const verificationIsStale = (
    passport.post_submission_verification?.stale_after_staff_edit === true
  );
  const currentVerification = verificationIsStale
    ? null
    : passport.post_submission_verification;
  return (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-center gap-2 text-slate-900">
              <CheckCircle2 className="h-5 w-5 text-green-600" />
              <h3 className="text-base font-semibold">Review Fields</h3>
            </div>
            <Badge variant={PASSPORT_STATUS_COLORS[passport.status] || "default"} dot>
              {PASSPORT_STATUS_LABELS[passport.status] || passport.status}
            </Badge>
          </div>
          <div className="grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm sm:grid-cols-2">
            <MetaItem label="Submitted" value={formatDateTime(passport.created_at)} />
            <MetaItem label="Updated" value={formatDateTime(passport.updated_at)} />
            <MetaItem
              label="Expiry"
              value={formatPassportDateForUi(reviewFields.date_of_expiry) || "Not extracted"}
            />
            {passport.qualifier_enabled_snapshot && (
              <MetaItem
                label="Relation with Qualifier"
                value={passport.qualifier_is_self
                  ? "Self"
                  : passport.qualifier_relation_label || "Not selected"}
              />
            )}
            {currentVerification && (
              <>
                <MetaItem
                  label="AI decision"
                  value={
                    PASSPORT_STATUS_LABELS[
                      currentVerification.verification_status
                    ] || currentVerification.verification_status
                  }
                />
                <MetaItem
                  label="Verification confidence"
                  value={formatConfidence(
                    getPassportVerificationConfidence(currentVerification),
                  )}
                />
              </>
            )}
            {!verificationIsStale && passport.post_submission_verified_at && (
              <MetaItem
                label="AI verification completed"
                value={formatDateTime(passport.post_submission_verified_at)}
              />
            )}
            {reviewerLabel && (
              <MetaItem label="Reviewed by" value={reviewerLabel} />
            )}
            {passport.verification_reviewed_at && (
              <MetaItem
                label="Staff reviewed"
                value={formatDateTime(passport.verification_reviewed_at)}
              />
            )}
          </div>
          {verificationIsStale && (
            <div
              className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-900"
              role="status"
              aria-live="polite"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <p>
                Passport details changed. The previous AI verification is no longer
                valid. Review the current fields and approve this passport again.
              </p>
            </div>
          )}
          {workflowStatusMessage && (
            <p className="text-sm leading-6 text-blue-700" role="status" aria-live="polite">
              {workflowStatusMessage}
            </p>
          )}
          {approvalFeedback && (
            <div
              className={
                approvalFeedback.kind === "success"
                  ? "rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800"
                  : "rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800"
              }
              role="status"
              aria-live="polite"
            >
              {approvalFeedback.message}
            </div>
          )}
          {currentVerification?.explanation && (
            <p className="text-sm leading-6 text-slate-600">
              {currentVerification.explanation}
            </p>
          )}
        </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 break-all text-sm font-medium text-slate-800">{value}</div>
    </div>
  );
}
