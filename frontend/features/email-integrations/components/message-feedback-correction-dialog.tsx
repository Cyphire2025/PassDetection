import { Button } from "@/components/ui";
import { formatEmailLabel } from "../utils/email-integrations";
import { EmailDialog, EmailNotice } from "./email-integrations-ui";
import { EMAIL_INTENT_OPTIONS, feedbackCorrectionCopy, isCorrectionReady, readActionError } from "./message-activity-model";
import { MessageFeedbackLinks } from "./message-feedback-links";
import { MessageFeedbackDeadline } from "./message-feedback-deadline";
import type { useMessageFeedbackController } from "./use-message-feedback-controller";
type FeedbackController = ReturnType<typeof useMessageFeedbackController>;

export function MessageFeedbackCorrectionDialog({ controller }: { controller: FeedbackController; }) {
  const {
    feedback,
    correctionField,
    intelligence,
    resetCorrection,
    correctionText,
    setCorrectionText,
    selectedIntent,
    setSelectedIntent,
    selectedPriority,
    setSelectedPriority,
    selectedGroupId,
    groups,
    passengers,
    selectedDeadlineId,
    deadlineValue,
    notificationExpected,
    setNotificationExpected,
    correctionNote,
    setCorrectionNote,
    submitCorrection,
  } = controller;
  return (
    <>
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
            <MessageFeedbackLinks controller={controller} />
            <MessageFeedbackDeadline controller={controller} />
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
    </>
  );
}
