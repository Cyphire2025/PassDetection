"use client";
import { useState } from "react";
import { Input } from "@/components/ui/input";
import { PassportDateInput } from "@/components/shared/passport-date-input";
import { formatPassportNationality } from "@/lib/utils/passport-country";
import {
  PASSPORT_REVIEW_FIELDS as REVIEW_FIELDS,
  getPassportFieldReview,
  getPassportFieldReviewClassName,
  formatPassportVerificationReason,
  formatPassportFieldReviewConfidence,
  type PassportFieldReview,
} from "../utils/passport-review";
import type { ReviewFieldsCardProps } from "./passport-review-types";
import { toLabel, valuesMatch, formatConflictValue, todayIsoDate, yesterdayIsoDate } from "./passport-review-model";

export function PassportReviewFields({ passport, validation, reviewFields, onChange }: Pick<ReviewFieldsCardProps, "passport" | "validation"> & {
  reviewFields: Record<string, string>;
  onChange: (key: string, value: string) => void;
}) {
  return (
        <div className="grid gap-4 sm:grid-cols-2">
          {REVIEW_FIELDS.map((key) => {
            const isDate = key === "date_of_birth" || key === "date_of_issue" || key === "date_of_expiry";
            const isCountry = key === "nationality";
            const fieldReview = getPassportFieldReview(passport, validation, key);
            const fieldClassName = getPassportFieldReviewClassName(fieldReview?.verdict);
            return (
              <div key={key} className="space-y-1.5">
                <span className="flex flex-wrap items-center gap-2 text-xs font-medium uppercase tracking-wide text-slate-400">
                  <span>{toLabel(key)}</span>
                  {fieldReview && (
                    <span className={fieldReview.verdict === "incorrect"
                      ? "rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-800"
                      : "rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-800"}
                    >
                      {fieldReview.label}
                    </span>
                  )}
                </span>
                {isCountry ? (
                  <PassportCountryTextField
                    key={`${key}:${reviewFields[key] ?? ""}`}
                    value={reviewFields[key] ?? ""}
                    onChange={(value) => onChange(key, value)}
                    className={fieldClassName}
                    ariaLabel={toLabel(key)}
                  />
                ) : isDate ? (
                  <PassportDateInput
                    value={reviewFields[key] ?? ""}
                    onValueChange={(value) => onChange(key, value)}
                    minIso="1900-01-01"
                    maxIso={key === "date_of_birth" ? yesterdayIsoDate() : key === "date_of_issue" ? todayIsoDate() : "2200-12-31"}
                    aria-label={toLabel(key)}
                    className={`h-10 rounded-lg ${fieldClassName}`}
                  />
                ) : (
                  <Input
                    type="text"
                    value={reviewFields[key] ?? ""}
                    onChange={(event) => onChange(key, event.target.value)}
                    placeholder="Not extracted"
                    aria-label={toLabel(key)}
                    className={`h-10 rounded-lg ${fieldClassName}`}
                  />
                )}
                {fieldReview && (
                  <FieldReviewMessage
                    review={fieldReview}
                    editedValue={reviewFields[key] ?? ""}
                  />
                )}
              </div>
            );
          })}
        </div>
  );
}

function FieldReviewMessage({
  review,
  editedValue,
}: {
  review: PassportFieldReview;
  editedValue: string;
}) {
  const observedValue = review.observed_value?.trim() ?? "";
  const showObservedValue = Boolean(observedValue) && !valuesMatch(observedValue, editedValue);
  const messageClass = review.verdict === "incorrect" ? "text-red-700" : "text-amber-700";
  const reason = formatPassportVerificationReason(review.reason_code);
  const confidence = formatPassportFieldReviewConfidence(review);

  return (
    <p className={`text-xs leading-5 ${messageClass}`}>
      {reason}
      {showObservedValue && (
        <>
          {" "}AI observed <span className="font-semibold">{formatConflictValue(review.field, observedValue)}</span>.
        </>
      )}
      {confidence && <> {confidence}.</>}
    </p>
  );
}

function PassportCountryTextField({
  value,
  onChange,
  className,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  className?: string;
  ariaLabel: string;
}) {
  const formattedValue = formatPassportNationality(value) || value;
  const [draftValue, setDraftValue] = useState(formattedValue);
  const [isDirty, setIsDirty] = useState(false);

  return (
    <Input
      type="text"
      value={draftValue}
      onChange={(event) => {
        setDraftValue(event.target.value);
        setIsDirty(true);
      }}
      onBlur={() => {
        if (!isDirty) return;
        onChange(draftValue);
        setIsDirty(false);
      }}
      placeholder="Not extracted"
      aria-label={ariaLabel}
      className={`h-10 rounded-lg ${className ?? "border-slate-200 bg-white"}`}
    />
  );
}
