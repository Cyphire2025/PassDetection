"use client";
import { Button, Card, CardContent } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import { RefreshCw } from "lucide-react";
import type { EmailIntelligenceDetail } from "../types";
import { formatEmailLabel } from "../utils/email-integrations";
import { EmailDialog, EmailNotice } from "./email-integrations-ui";
import {
  EMAIL_INTENT_OPTIONS,
  feedbackCorrectionCopy,
  feedbackCorrectionOptions,
  isCorrectionReady,
  readActionError,
  toLocalDateTimeInput,
} from "./message-activity-model";
import { useMessageFeedbackController } from "./use-message-feedback-controller";
export function IntelligenceFeedback(props: {
  messageId: string;
  intelligence: EmailIntelligenceDetail;
}) {
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
    resetCorrection,
    correctionText,
    setCorrectionText,
    selectedIntent,
    setSelectedIntent,
    selectedPriority,
    setSelectedPriority,
    selectedGroupId,
    groups,
    setSelectedGroupId,
    setSelectedPassengerIds,
    passengers,
    selectedPassengerIds,
    selectedDeadlineId,
    setSelectedDeadlineId,
    setDeadlineValue,
    deadlineValue,
    notificationExpected,
    setNotificationExpected,
    correctionNote,
    setCorrectionNote,
    submitCorrection,
    sendDismissal,
  } = useMessageFeedbackController(props);
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

        {correctionField && (
          <EmailDialog
            title={feedbackCorrectionCopy(correctionField).title}
            description="The correction updates this operational brief immediately and is recorded in its audit trail. It never changes or sends the source email."
            isBusy={feedback.isPending}
            onClose={() => {
              if (feedback.isPending) return;
              resetCorrection();
              feedback.reset();
            }}
          >
            <div className="space-y-4">
              {correctionField === "summary" && (
                <label className="block text-sm font-medium text-slate-700">
                  Corrected summary
                  <textarea
                    required
                    value={correctionText}
                    maxLength={2000}
                    rows={6}
                    className="mt-1.5 w-full resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none transition-colors focus:border-transparent focus:ring-2 focus:ring-blue-600"
                    onChange={(event) => setCorrectionText(event.target.value)}
                  />
                </label>
              )}
              {correctionField === "intent" && (
                <label className="block text-sm font-medium text-slate-700">
                  Correct category
                  <select
                    value={selectedIntent}
                    disabled={feedback.isPending}
                    onChange={(event) => setSelectedIntent(event.target.value)}
                    className="mt-1.5 block h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:bg-slate-100"
                  >
                    {EMAIL_INTENT_OPTIONS.map((intent) => (
                      <option key={intent} value={intent}>
                        {formatEmailLabel(intent)}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {correctionField === "priority" && (
                <label className="block text-sm font-medium text-slate-700">
                  Correct priority
                  <select
                    value={selectedPriority}
                    disabled={feedback.isPending}
                    onChange={(event) =>
                      setSelectedPriority(
                        event.target.value as
                          | "low"
                          | "normal"
                          | "high"
                          | "urgent",
                      )
                    }
                    className="mt-1.5 block h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:bg-slate-100"
                  >
                    {(["low", "normal", "high", "urgent"] as const).map(
                      (priority) => (
                        <option key={priority} value={priority}>
                          {formatEmailLabel(priority)}
                        </option>
                      ),
                    )}
                  </select>
                </label>
              )}
              {(correctionField === "linked_group" ||
                correctionField === "linked_passengers") && (
                <label className="block text-sm font-medium text-slate-700">
                  Correct group
                  <select
                    value={selectedGroupId}
                    disabled={
                      groups.isLoading || groups.isError || feedback.isPending
                    }
                    onChange={(event) => {
                      setSelectedGroupId(event.target.value);
                      setSelectedPassengerIds([]);
                    }}
                    className="mt-1.5 block h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:bg-slate-100"
                  >
                    <option value="">Select a visible group</option>
                    {groups.data?.groups.map((group) => (
                      <option key={group.id} value={group.id}>
                        {group.name}
                        {group.destination ? ` — ${group.destination}` : ""}
                        {group.travel_date ? ` — ${group.travel_date}` : ""}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {correctionField === "linked_passengers" && (
                <fieldset
                  disabled={
                    !selectedGroupId ||
                    passengers.isLoading ||
                    passengers.isError ||
                    feedback.isPending
                  }
                  className="space-y-2"
                >
                  <legend className="text-sm font-medium text-slate-700">
                    Correct passengers
                  </legend>
                  <p className="text-xs text-slate-500">
                    Select every passenger referenced by this email. Leave all
                    unselected to remove the current passenger links.
                  </p>
                  <div className="max-h-56 space-y-2 overflow-y-auto rounded-lg border border-slate-200 p-3">
                    {passengers.data?.passengers.length ? (
                      passengers.data.passengers.map((passenger) => (
                        <label
                          key={passenger.id}
                          className="flex items-start gap-2 text-sm text-slate-700"
                        >
                          <input
                            type="checkbox"
                            checked={selectedPassengerIds.includes(
                              passenger.id,
                            )}
                            className="mt-0.5 h-4 w-4 rounded border-slate-300"
                            onChange={(event) =>
                              setSelectedPassengerIds((current) =>
                                event.target.checked
                                  ? [...current, passenger.id]
                                  : current.filter((id) => id !== passenger.id),
                              )
                            }
                          />
                          <span>{passenger.name}</span>
                        </label>
                      ))
                    ) : (
                      <p className="text-sm text-slate-500">
                        {selectedGroupId
                          ? "No available passengers were found in this group."
                          : "Select a group to load its passengers."}
                      </p>
                    )}
                  </div>
                </fieldset>
              )}
              {correctionField === "deadline" && (
                <div className="space-y-4">
                  {intelligence.deadlines.length > 0 && (
                    <label className="block text-sm font-medium text-slate-700">
                      Deadline to correct
                      <select
                        required
                        value={selectedDeadlineId}
                        disabled={feedback.isPending}
                        onChange={(event) => {
                          const deadlineId = event.target.value;
                          const selected = intelligence.deadlines.find(
                            (deadline) => deadline.id === deadlineId,
                          );
                          setSelectedDeadlineId(deadlineId);
                          setDeadlineValue(
                            toLocalDateTimeInput(selected?.due_at),
                          );
                        }}
                        className="mt-1.5 block h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:bg-slate-100"
                      >
                        <option value="">Select a detected deadline</option>
                        {intelligence.deadlines.map((deadline) => (
                          <option key={deadline.id} value={deadline.id}>
                            {deadline.source_phrase}
                            {" — "}
                            {deadline.due_at
                              ? formatDateTime(deadline.due_at)
                              : "No date detected"}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <label className="block text-sm font-medium text-slate-700">
                    Correct date and time
                    <input
                      type="datetime-local"
                      required
                      value={deadlineValue}
                      disabled={feedback.isPending}
                      onChange={(event) => setDeadlineValue(event.target.value)}
                      className="mt-1.5 block h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:bg-slate-100"
                    />
                    <span className="mt-1 block text-xs font-normal text-slate-500">
                      Enter the deadline in your device&apos;s timezone.
                    </span>
                  </label>
                </div>
              )}
              {correctionField === "notification" && (
                <fieldset className="space-y-2">
                  <legend className="text-sm font-medium text-slate-700">
                    Expected notification
                  </legend>
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input
                      type="radio"
                      name="notification-expected"
                      checked={notificationExpected}
                      onChange={() => setNotificationExpected(true)}
                    />
                    This email should notify me
                  </label>
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input
                      type="radio"
                      name="notification-expected"
                      checked={!notificationExpected}
                      onChange={() => setNotificationExpected(false)}
                    />
                    This email should not notify me
                  </label>
                </fieldset>
              )}
              <label className="block text-sm font-medium text-slate-700">
                Note{" "}
                <span className="font-normal text-slate-500">(optional)</span>
                <textarea
                  value={correctionNote}
                  maxLength={1000}
                  rows={3}
                  className="mt-1.5 w-full resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none transition-colors focus:border-transparent focus:ring-2 focus:ring-blue-600"
                  onChange={(event) => setCorrectionNote(event.target.value)}
                />
              </label>
              {(correctionField === "linked_group" ||
                correctionField === "linked_passengers") &&
                (groups.isError || passengers.isError) && (
                  <EmailNotice tone="error">
                    Visible group or passenger choices could not be loaded.
                    Close this dialog and try again.
                  </EmailNotice>
                )}
              {feedback.isError && (
                <EmailNotice tone="error">
                  {readActionError(
                    feedback.error,
                    "The correction could not be saved.",
                  )}
                </EmailNotice>
              )}
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  disabled={feedback.isPending}
                  onClick={() => {
                    resetCorrection();
                    feedback.reset();
                  }}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  isLoading={feedback.isPending}
                  disabled={
                    !isCorrectionReady({
                      field: correctionField,
                      correctionText,
                      selectedIntent,
                      selectedGroupId,
                      selectedDeadlineId,
                      hasExistingDeadlines: intelligence.deadlines.length > 0,
                      deadlineValue,
                    }) ||
                    ((correctionField === "linked_group" ||
                      correctionField === "linked_passengers") &&
                      groups.isError) ||
                    (correctionField === "linked_passengers" &&
                      passengers.isError)
                  }
                  onClick={submitCorrection}
                >
                  Save correction
                </Button>
              </div>
            </div>
          </EmailDialog>
        )}
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
