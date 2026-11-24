import type { useMessageFeedbackController } from "./use-message-feedback-controller";
type FeedbackController = ReturnType<typeof useMessageFeedbackController>;

export function MessageFeedbackLinks({ controller }: { controller: FeedbackController; }) {
  const {
    selectedPassengerIds,
    feedback,
    correctionField,
    selectedGroupId,
    groups,
    setSelectedGroupId,
    setSelectedPassengerIds,
    passengers,
  } = controller;
  const selectedIds = new Set(selectedPassengerIds);
  return (
    <>
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
                    checked={selectedIds.has(passenger.id)}
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
    </>
  );
}
