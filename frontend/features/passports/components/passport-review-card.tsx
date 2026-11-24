"use client";
import { Card, CardContent } from "@/components/ui/card";
import { usePassportFieldReview } from "./use-passport-field-review";
import { PassportReviewStatus } from "./passport-review-status";
import { PassportReviewFields } from "./passport-review-fields";
import { PassportReviewActions } from "./passport-review-actions";
import { ExtractionConflictPanel } from "./passport-review-conflicts";
import { ReextractStatus } from "./passport-reextract-status";
import type { ReviewFieldsCardProps } from "./passport-review-types";

export function ReviewFieldsCard(props: ReviewFieldsCardProps) {
  const review = usePassportFieldReview(props);
  return (
    <Card className="rounded-3xl">
      <CardContent className="space-y-5 p-5">
        <PassportReviewStatus passport={props.passport} reviewerLabel={props.reviewerLabel}
          approvalFeedback={props.approvalFeedback} reviewFields={review.reviewFields} />
        <ReextractStatus passport={props.passport} feedback={props.reextractFeedback} isReextracting={props.isReextracting} />
        {props.conflicts.length > 0 && (
          <ExtractionConflictPanel conflicts={props.conflicts} reviewFields={review.reviewFields}
            onSelect={(field, value) => { review.handleFieldChange(field, value); props.onFormError(null); }} />
        )}
        <PassportReviewFields passport={props.passport} validation={props.validation}
          reviewFields={review.reviewFields} onChange={review.handleFieldChange} />
        <PassportReviewActions passport={props.passport} isSaving={props.isSaving} isReextracting={props.isReextracting}
          isRetryingAiVerification={props.isRetryingAiVerification} canReextract={props.canReextract}
          canRetryAiVerification={props.canRetryAiVerification} formError={props.formError} onReextract={props.onReextract}
          reviewReason={review.reviewReason} setReviewReason={review.setReviewReason}
          handleConfirm={review.handleConfirm} handleRetryAiVerification={review.handleRetryAiVerification} />
      </CardContent>
    </Card>
  );
}
