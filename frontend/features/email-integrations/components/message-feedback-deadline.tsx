import { formatDateTime } from "@/lib/utils/format";
import { toLocalDateTimeInput } from "./message-activity-model";
import type { useMessageFeedbackController } from "./use-message-feedback-controller";
type FeedbackController = ReturnType<typeof useMessageFeedbackController>;

export function MessageFeedbackDeadline({ controller }: { controller: FeedbackController; }) {
  const {
    feedback,
    correctionField,
    intelligence,
    selectedDeadlineId,
    setSelectedDeadlineId,
    setDeadlineValue,
    deadlineValue,
  } = controller;
  return (
    <>
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
    </>
  );
}
