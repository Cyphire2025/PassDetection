import type { ComposerController } from "./message-composer";
import { fieldClass } from "./workspace-ui";

interface AudienceFilterProps {
  model: ComposerController;
  changeFilter: (patch: Partial<ComposerController["state"]>) => void;
}

export function ComposerAudienceFilters({ model, changeFilter }: AudienceFilterProps) {
  return (<>
    {model.definition.audience === "reminder" && (
      <fieldset disabled={model.pending} className="space-y-3">
        <legend className="mb-2 text-xs font-medium text-slate-600">
          Reminder audience
        </legend>
        <div className="flex flex-wrap gap-3">
          {[
            { value: "all" as const, label: "Everyone" },
            {
              value: "not_submitted" as const,
              label: "Only people who haven’t submitted",
            },
          ].map((option) => (
            <label
              key={option.value}
              className={`flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm ${model.state.reminderAudience === option.value ? "border-blue-300 bg-blue-50 text-blue-800" : "border-slate-200 text-slate-600"}`}
            >
              <input
                type="radio"
                name="reminder-audience"
                value={option.value}
                checked={model.state.reminderAudience === option.value}
                onChange={() =>
                  changeFilter({ reminderAudience: option.value })
                }
                className="accent-blue-600"
              />
              {option.label}
            </label>
          ))}
        </div>
        {model.state.reminderAudience === "not_submitted" &&
          model.activeLinks.length > 1 && (
            <label className="block max-w-md text-xs font-medium text-slate-600">
              Submission group
              <select
                className={`mt-1.5 ${fieldClass}`}
                value={model.reminderGroupId ?? ""}
                onChange={(event) =>
                  changeFilter({ reminderGroupId: event.target.value })
                }
              >
                <option value="">Choose the linked group to check</option>
                {model.activeLinks.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          )}
        {model.state.reminderAudience === "not_submitted" &&
          model.activeLinks.length === 0 && (
            <p role="alert" className="text-xs text-amber-800">
              Link an active submission group before using this audience.
            </p>
          )}
      </fieldset>
    )}
    {model.definition.audience === "update" && (
      <fieldset
        disabled={model.pending}
        className="grid gap-4 sm:grid-cols-3"
      >
        <legend className="mb-3 text-xs font-medium text-slate-600">
          Both submission and delivery filters apply together
        </legend>
        <label className="text-xs font-medium text-slate-600">
          Document submission
          <select
            value={model.state.submission}
            onChange={(event) =>
              changeFilter({
                submission: event.target
                  .value as ComposerController["state"]["submission"],
              })
            }
            className={`mt-1.5 ${fieldClass}`}
          >
            <option value="all">Everyone</option>
            <option value="submitted">Submitted</option>
            <option value="not_submitted">Not submitted</option>
          </select>
        </label>
        <label className="text-xs font-medium text-slate-600">
          Document delivery
          <select
            value={model.state.distribution}
            onChange={(event) =>
              changeFilter({
                distribution: event.target
                  .value as ComposerController["state"]["distribution"],
              })
            }
            className={`mt-1.5 ${fieldClass}`}
          >
            <option value="all">Any delivery status</option>
            <option value="sent">Sent</option>
            <option value="pending">Pending</option>
          </select>
        </label>
        <label className="text-xs font-medium text-slate-600">
          Document type
          <select
            value={model.state.documentType}
            onChange={(event) =>
              changeFilter({ documentType: event.target.value })
            }
            className={`mt-1.5 ${fieldClass}`}
          >
            <option value="visa">Visa</option>
            <option value="flight_ticket">Flight ticket · departure</option>
            <option value="flight_ticket_arrival">
              Flight ticket · return
            </option>
            <option value="flight_ticket_domestic">
              Domestic flight · departure
            </option>
            <option value="flight_ticket_domestic_arrival">
              Domestic flight · return
            </option>
          </select>
        </label>
      </fieldset>
    )}
    {model.definition.message_type === "passport_link" && (
      <label className="flex items-start gap-3 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
        <input
          type="checkbox"
          checked={model.state.includePreviousRecipients}
          disabled={model.pending}
          onChange={(event) =>
            changeFilter({
              includePreviousRecipients: event.target.checked,
            })
          }
          className="mt-0.5 h-4 w-4 accent-blue-600"
        />
        <span>
          Include people who received a previous passport link
          <span className="mt-1 block text-xs text-slate-500">
            This creates a new message with its own delivery history.
            Pending or unconfirmed sends stay excluded.
          </span>
        </span>
      </label>
    )}
  </>);
}
