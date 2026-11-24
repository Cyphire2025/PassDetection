"use client";
import { useRef, useState } from "react";
import { getPassportTextField } from "@/lib/utils/passport-fields";
import {
  PASSPORT_REVIEW_FIELDS as REVIEW_FIELDS,
  cleanPassportReviewFields,
  getStaffApprovalErrorFeedback,
} from "../utils/passport-review";
import { hasValidReviewDates, readReviewActionError } from "./passport-review-model";
import type { ReviewFieldsCardProps } from "./passport-review-types";

export function usePassportFieldReview({ passport, sourceFields, isSaving, isRetryingAiVerification, onFormError, onStaffApprove, onConfirm, onRetryAiVerification }: ReviewFieldsCardProps) {
  const [reviewFields, setReviewFields] = useState<Record<string, string>>(
    () =>
      REVIEW_FIELDS.reduce<Record<string, string>>((fields, key) => {
        fields[key] = getPassportTextField(sourceFields, key);
        return fields;
      }, {}),
  );
  const [reviewReason, setReviewReason] = useState("");
  const reviewActionInFlightRef = useRef(false);
  const verificationRetryInFlightRef = useRef(false);

  const handleFieldChange = (key: string, value: string) => {
    setReviewFields((current) => ({ ...current, [key]: value }));
  };

  const handleConfirm = async () => {
    if (isSaving || reviewActionInFlightRef.current) return;
    const cleanedFields = cleanPassportReviewFields(reviewFields);

    if (Object.keys(cleanedFields).length === 0) {
      onFormError("Add at least one reviewed field before confirming.");
      return;
    }
    if (!hasValidReviewDates(cleanedFields)) {
      onFormError("Enter valid passport dates in DD/MM/YYYY format. Check that birth, issue, and expiry are chronological and no entered birth or issue date is in the future.");
      return;
    }

    onFormError(null);
    reviewActionInFlightRef.current = true;
    try {
      if (passport.status === "needs_review") {
        await onStaffApprove(cleanedFields, reviewReason.trim() || undefined);
      } else {
        await onConfirm(cleanedFields);
      }
    } catch (error) {
      onFormError(
        passport.status === "needs_review"
          ? getStaffApprovalErrorFeedback(error).message
          : readReviewActionError(
            error,
            "Could not save the reviewed passport fields. Please try again.",
          ),
      );
    } finally {
      reviewActionInFlightRef.current = false;
    }
  };

  const handleRetryAiVerification = async () => {
    if (
      isRetryingAiVerification
      || verificationRetryInFlightRef.current
    ) return;
    verificationRetryInFlightRef.current = true;
    onFormError(null);
    try {
      await onRetryAiVerification();
    } catch (error) {
      onFormError(readReviewActionError(
        error,
        "Could not retry AI verification. The existing review remains unchanged.",
      ));
    } finally {
      verificationRetryInFlightRef.current = false;
    }
  };
  return { reviewFields, reviewReason, setReviewReason, handleFieldChange, handleConfirm, handleRetryAiVerification };
}
