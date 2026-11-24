import { Button } from "@/components/ui";
import type { PassportSubmission } from "@/types/passport.types";
import { Loader2, RotateCcw } from "lucide-react";
import { useRef, useState } from "react";
import { useReextractPassportSubmission } from "../hooks/use-passports";
import { getReextractFeedback, needsReextraction } from "../utils/passport-reextract";

export function ReextractPassportControl({
  passport,
  compact = false,
}: {
  passport: PassportSubmission;
  compact?: boolean;
}) {
  const reextractMutation = useReextractPassportSubmission();
  const [feedback, setFeedback] = useState<{
    tone: "success" | "warning" | "error";
    message: string;
  } | null>(null);
  const reextractInFlightRef = useRef(false);
  const isProcessing = passport.extraction_status === "processing"
    || (passport.status === "submitted" && feedback !== null);
  const backgroundFinished = feedback?.tone === "warning" && !isProcessing;
  const effectiveFeedback = backgroundFinished
    ? getReextractFeedback(passport)
    : feedback;

  const handleReextract = async (
    event: React.MouseEvent<HTMLButtonElement>,
  ) => {
    event.stopPropagation();
    if (reextractMutation.isPending || reextractInFlightRef.current) return;
    reextractInFlightRef.current = true;
    setFeedback(null);
    try {
      const result = await reextractMutation.mutateAsync(passport.id);
      if (result.outcome === "timed_out") {
        setFeedback({
          tone: "warning",
          message: "Still processing. This row will refresh automatically.",
        });
        return;
      }
      if (result.outcome === "failed") {
        setFeedback({
          tone: "error",
          message:
            "Automatic extraction failed. The saved image is unchanged; try again.",
        });
        return;
      }
      setFeedback(getReextractFeedback(result.submission));
    } catch (error) {
      setFeedback({
        tone: "error",
        message:
          error instanceof Error
            ? error.message
            : "Could not start re-extraction. Please try again.",
      });
    } finally {
      reextractInFlightRef.current = false;
    }
  };

  if (!needsReextraction(passport) && !isProcessing && !effectiveFeedback)
    return null;

  return (
    <div
      className={compact ? "max-w-52 text-right" : "w-full"}
      onClick={(event) => event.stopPropagation()}
    >
      {(needsReextraction(passport) || isProcessing || reextractMutation.isPending) && <Button
        variant="secondary"
        size={compact ? "sm" : "md"}
        className={compact ? "gap-2" : "w-full gap-2"}
        disabled={reextractMutation.isPending || isProcessing || !needsReextraction(passport)}
        onClick={(event) => void handleReextract(event)}
        aria-busy={reextractMutation.isPending || isProcessing}
      >
        {reextractMutation.isPending || isProcessing ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <RotateCcw className="h-4 w-4" aria-hidden="true" />
        )}
        {reextractMutation.isPending
          ? "Extracting"
          : isProcessing
            ? "Processing"
            : effectiveFeedback?.tone === "error"
              ? "Try again"
              : "Re-extract"}
      </Button>}
      {effectiveFeedback && (
        <p
          className={`mt-1.5 text-xs leading-4 ${
            effectiveFeedback.tone === "success"
              ? "text-emerald-700"
              : effectiveFeedback.tone === "warning"
                ? "text-amber-700"
                : "text-red-700"
          }`}
          role={effectiveFeedback.tone === "error" ? "alert" : "status"}
        >
          {effectiveFeedback.message}
        </p>
      )}
    </div>
  );
}
