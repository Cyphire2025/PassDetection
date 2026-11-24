"use client";

import { Button, Card, CardContent } from "@/components/ui";
import { RefreshCw } from "lucide-react";
import type { EmailIntelligenceDetail } from "../types";
import { EmailDialog, EmailNotice } from "./email-integrations-ui";
import { feedbackCorrectionOptions, readActionError } from "./message-activity-model";
import { useMessageFeedbackController } from "./use-message-feedback-controller";
import { MessageFeedbackCorrectionDialog } from "./message-feedback-correction-dialog";

export function IntelligenceFeedback(props: { messageId: string; intelligence: EmailIntelligenceDetail; }) {
  const controller = useMessageFeedbackController(props);
  const {
    isDismissed,
    isConfirmed,
    canCorrect,
    isFailed,
    successMessage,
    retryAnalysis,
    feedback,
    correctionField,
    dismissOpen,
    canReview,
    sendConfirmation,
    intelligence,
    openCorrection,
    currentBriefState,
    setDismissSnapshot,
    setDismissOpen,
    setSuccessMessage,
    sendDismissal,
  } = controller;
  return (
    <Card className="border-dashed">
      <CardContent className="space-y-3 p-5">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">
            Improve this analysis
          </h3>
          <p className="mt-1 text-xs text-slate-500">
            Feedback is saved with this analysis. The source email is unchanged.
          </p>
        </div>
        {isDismissed && (
          <EmailNotice tone="info">
            This AI brief is currently ignored. You can still report a missed
            match, deadline, or classification; the source email will not be
            changed.
          </EmailNotice>
        )}
        {isConfirmed && (
          <EmailNotice tone="success">
            You confirmed this AI brief. Corrections and dismissal remain
            auditable if the operational facts change.
          </EmailNotice>
        )}
        {!canCorrect && !isFailed && (
          <EmailNotice tone="info">
            Feedback becomes available after the AI brief finishes.
          </EmailNotice>
        )}
        {isFailed && (
          <EmailNotice tone="error">
            This AI brief could not be completed. Try the analysis again. The source email is unchanged.
          </EmailNotice>
        )}
        {successMessage && (
          <EmailNotice tone="success">{successMessage}</EmailNotice>
        )}
        {retryAnalysis.isError && (
          <EmailNotice tone="error">
            {readActionError(
              retryAnalysis.error,
              "The AI brief could not be queued for retry.",
            )}
          </EmailNotice>
        )}
        {feedback.isError && correctionField === null && !dismissOpen && (
          <EmailNotice tone="error">
            {readActionError(feedback.error, "Feedback could not be saved.")}
          </EmailNotice>
        )}
        {canCorrect && (
          <div className="flex flex-wrap gap-2">
            {canReview && !isConfirmed && (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={feedback.isPending}
                onClick={sendConfirmation}
              >
                Looks right
              </Button>
            )}
            {feedbackCorrectionOptions(intelligence).map((option) => (
              <Button
                key={`${option.field}-${option.buttonLabel}`}
                type="button"
                size="sm"
                variant="secondary"
                disabled={feedback.isPending}
                onClick={() => openCorrection(option)}
              >
                {option.buttonLabel}
              </Button>
            ))}
            {canReview && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={feedback.isPending}
                onClick={() => {
                  const snapshot = currentBriefState();
                  if (!snapshot) return;
                  feedback.reset();
                  setDismissSnapshot(snapshot);
                  setDismissOpen(true);
                }}
              >
                Not useful
              </Button>
            )}
          </div>
        )}
        {isFailed && (
          <Button
            type="button"
            size="sm"
            variant="secondary"
            leftIcon={<RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />}
            isLoading={retryAnalysis.isPending}
            onClick={() => {
              setSuccessMessage(null);
              retryAnalysis.reset();
              retryAnalysis.mutate(intelligence.id, {
                onSuccess: (response) => {
                  setSuccessMessage(response.message);
                },
              });
            }}
          >
            Retry analysis
          </Button>
        )}

        <MessageFeedbackCorrectionDialog controller={controller} />
        {dismissOpen && (
          <EmailDialog
            title="Dismiss this AI brief?"
            description="This removes the brief and its open proposals, deadlines, and drafts from active AI views. It does not alter or send the source email."
            isBusy={feedback.isPending}
            onClose={() => {
              if (feedback.isPending) return;
              setDismissOpen(false);
              setDismissSnapshot(null);
              feedback.reset();
            }}
          >
            <div className="space-y-4">
              <EmailNotice tone="warning">
                Use this only when the full brief is not useful. Individual
                corrections can be recorded without closing the work.
              </EmailNotice>
              {feedback.isError && (
                <EmailNotice tone="error">
                  {readActionError(
                    feedback.error,
                    "The AI brief could not be dismissed.",
                  )}
                </EmailNotice>
              )}
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  disabled={feedback.isPending}
                  onClick={() => {
                    setDismissOpen(false);
                    setDismissSnapshot(null);
                    feedback.reset();
                  }}
                >
                  Keep brief
                </Button>
                <Button
                  type="button"
                  variant="danger"
                  isLoading={feedback.isPending}
                  onClick={sendDismissal}
                >
                  Dismiss AI brief
                </Button>
              </div>
            </div>
          </EmailDialog>
        )}
      </CardContent>
    </Card>
  );
}
