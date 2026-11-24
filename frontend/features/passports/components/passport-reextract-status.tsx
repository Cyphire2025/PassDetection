"use client";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import type { PassportSubmission } from "@/types/passport.types";
import { getReextractFeedback } from "../utils/passport-reextract";
import type { ReextractFeedback } from "./passport-review-types";
import { processingStageLabel } from "./passport-review-model";

export function ReextractStatus({
  passport,
  feedback,
  isReextracting,
}: {
  passport: PassportSubmission;
  feedback: ReextractFeedback | null;
  isReextracting: boolean;
}) {
  const isProcessing = isReextracting || passport.extraction_status === "processing"
    || (passport.status === "submitted" && feedback !== null);
  const backgroundFinished = feedback?.tone === "warning" && !isProcessing;
  const effectiveFeedback = backgroundFinished
    ? getReextractFeedback(passport)
    : feedback;
  if (!effectiveFeedback && !isProcessing) return null;

  const tone = isProcessing && effectiveFeedback?.tone !== "warning"
    ? "processing"
    : effectiveFeedback?.tone ?? "processing";
  const styles = {
    processing: "border-blue-200 bg-blue-50 text-blue-900",
    success: "border-emerald-200 bg-emerald-50 text-emerald-900",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
    error: "border-red-200 bg-red-50 text-red-900",
  }[tone];
  const message = isProcessing
    ? passport.status === "submitted"
      ? "AI verification is queued or running for all passport fields."
      : processingStageLabel(passport.processing_stage ?? passport.processing_job_status)
    : effectiveFeedback?.message;

  return (
    <div className={`rounded-2xl border p-4 ${styles}`} role={tone === "error" ? "alert" : "status"} aria-live="polite">
      <div className="flex items-start gap-3">
        {isProcessing ? (
          <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin" aria-hidden="true" />
        ) : tone === "success" ? (
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
        ) : (
          <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
        )}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">
            {isProcessing ? "Re-extraction in progress" : tone === "success" ? "Re-extraction complete" : "Re-extraction update"}
          </p>
          <p className="mt-1 text-sm leading-5 opacity-90">{message}</p>
          {isProcessing && typeof passport.processing_progress === "number" && (
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/70" aria-hidden="true">
              <div
                className="h-full rounded-full bg-blue-600 transition-all duration-500"
                style={{ width: `${Math.max(8, Math.min(100, Math.round(passport.processing_progress * 100)))}%` }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
