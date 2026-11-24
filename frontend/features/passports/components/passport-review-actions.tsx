"use client";
import { Loader2, RotateCcw, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getPassportReviewActionState } from "../utils/passport-review";
import type { ReviewFieldsCardProps } from "./passport-review-types";

export function PassportReviewActions({ passport, isSaving, isReextracting, isRetryingAiVerification, canReextract, canRetryAiVerification,
  formError, reviewReason, setReviewReason, onReextract, handleConfirm, handleRetryAiVerification }: Pick<ReviewFieldsCardProps,
  "passport" | "isSaving" | "isReextracting" | "isRetryingAiVerification" | "canReextract" | "canRetryAiVerification" | "formError" | "onReextract"> & {
    reviewReason: string; setReviewReason: (value: string) => void;
    handleConfirm: () => Promise<void>; handleRetryAiVerification: () => Promise<void>;
  }) {
  const actionState = getPassportReviewActionState(passport.status, isSaving);
  return <>
        {passport.status === "needs_review" && (
          <label className="block text-sm font-medium text-slate-700">
            Review reason <span className="font-normal text-slate-400">(optional)</span>
            <textarea
              className="mt-1.5 min-h-20 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50"
              value={reviewReason}
              maxLength={240}
              disabled={isSaving}
              onChange={(event) => setReviewReason(event.target.value)}
              placeholder="Briefly describe why manual approval was required. Do not enter passport values."
            />
            <span className="mt-1 block text-xs font-normal text-slate-400">
              {reviewReason.length}/240 characters
            </span>
          </label>
        )}

        {formError && (
          <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {formError}
          </div>
        )}

        {(canReextract || passport.extraction_status === "processing") && (
          <Button
            variant="secondary"
            className="w-full gap-2"
            disabled={
              isReextracting
              || passport.extraction_status === "processing"
              || isSaving
              || isRetryingAiVerification
            }
            onClick={onReextract}
            aria-busy={isReextracting || passport.extraction_status === "processing"}
          >
            {isReextracting || passport.extraction_status === "processing" ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
            )}
            {isReextracting || passport.extraction_status === "processing"
              ? "Extracting saved passport"
              : "Re-extract Passport"}
          </Button>
        )}

        {canRetryAiVerification && (
          <Button
            type="button"
            variant="secondary"
            className="w-full gap-2"
            disabled={isRetryingAiVerification || isSaving || isReextracting}
            onClick={() => void handleRetryAiVerification()}
            aria-busy={isRetryingAiVerification}
          >
            {isRetryingAiVerification ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
            )}
            {isRetryingAiVerification
              ? "Starting AI verification"
              : "Retry AI Verification"}
          </Button>
        )}

        <Button
          onClick={() => void handleConfirm()}
          disabled={
            actionState.disabled
            || isRetryingAiVerification
            || isReextracting
          }
          className="w-full gap-2 bg-blue-600 text-white hover:bg-blue-700"
          aria-busy={isSaving}
        >
          {isSaving ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <Save className="h-4 w-4" aria-hidden="true" />
          )}
          {actionState.label}
        </Button>
  </>;
}
