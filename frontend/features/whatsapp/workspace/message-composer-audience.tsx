"use client";

import { useDeferredValue, useState } from "react";
import type { ComposerController } from "./message-composer";
import {
  EmptyWorkspace,
  fieldClass,
  tableClass,
  WorkspacePagination,
  WorkspaceSearch,
} from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";

export function ComposerAudience({ model }: { model: ComposerController }) {
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search).trim().toLocaleLowerCase();
  const [offset, setOffset] = useState(0);
  const matches = model.audience.filter(
    (recipient) =>
      !q ||
      `${recipient.name ?? ""} ${recipient.normalized_phone_number}`
        .toLocaleLowerCase()
        .includes(q),
  );
  const selected = new Set(model.selectedIds);
  const allMatchedSelected =
    matches.length > 0 &&
    matches.every((recipient) => selected.has(recipient.id));
  const changeFilter = (patch: Partial<ComposerController["state"]>) => {
    model.setState((current) => ({
      ...current,
      ...patch,
      recipientIds: null,
      previewRecipientId: null,
    }));
    setOffset(0);
  };
  return (
    <section className={styles.surface} aria-label="Message audience">
      <div className="space-y-5 p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">
              Recipients for this send
            </h3>
            <p className="mt-1 text-xs text-slate-500">
              Choose the audience, then select the people who should receive
              this message.
            </p>
          </div>
          <span
            aria-live="polite"
            className="text-xs tabular-nums text-slate-500"
          >
            {model.current
              ? `${model.selected.length} selected of ${model.audience.length} matching`
              : "Checking audience…"}
          </span>
        </div>
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
        <WorkspaceSearch
          value={search}
          onChange={(value) => {
            setSearch(value);
            setOffset(0);
          }}
          label="Search send recipients"
          placeholder="Search recipients by name or number…"
        >
          <button
            type="button"
            disabled={model.pending || !model.current}
            className="text-xs font-medium text-blue-700 disabled:opacity-40"
            onClick={() => {
              const next = new Set(model.selectedIds);
              for (const recipient of matches) {
                if (allMatchedSelected) next.delete(recipient.id);
                else next.add(recipient.id);
              }
              model.setState((current) => ({
                ...current,
                recipientIds: [...next],
                previewRecipientId: null,
              }));
            }}
          >
            {allMatchedSelected ? "Deselect matching" : "Select all matching"}
          </button>
        </WorkspaceSearch>
      </div>
      {matches.length === 0 ? (
        <EmptyWorkspace
          title={
            model.eligible.length === 0
              ? "No recipients available for this message"
              : model.current
                ? "No matching recipients"
                : "Checking recipients"
          }
          description={
            model.eligible.length === 0
              ? "Check welcome prerequisites and earlier deliveries in Recipients or Delivery history. For a new passport link, you can also include previous recipients."
              : model.current
                ? "Adjust your audience filters or clear the search."
                : "Recipients will appear after the audience has been checked."
          }
        />
      ) : (
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead>
              <tr>
                <th className="w-12">
                  <span className="sr-only">Selection</span>
                </th>
                <th>Recipient</th>
                <th>WhatsApp number</th>
              </tr>
            </thead>
            <tbody>
              {matches.slice(offset, offset + 25).map((recipient) => (
                <tr key={recipient.id}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Select ${recipient.name || recipient.normalized_phone_number}`}
                      checked={selected.has(recipient.id)}
                      disabled={model.pending}
                      className="h-4 w-4 accent-blue-600"
                      onChange={(event) =>
                        model.setState((current) => ({
                          ...current,
                          recipientIds: event.target.checked
                            ? [...new Set([...model.selectedIds, recipient.id])]
                            : model.selectedIds.filter(
                                (id) => id !== recipient.id,
                              ),
                          previewRecipientId: null,
                        }))
                      }
                    />
                  </td>
                  <td className="font-medium text-slate-800">
                    {recipient.name || "Unnamed recipient"}
                  </td>
                  <td className="tabular-nums text-slate-500">
                    {recipient.normalized_phone_number}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <WorkspacePagination
        total={matches.length}
        offset={offset}
        limit={25}
        onChange={setOffset}
        label="Send recipients"
        busy={model.pending}
      />
    </section>
  );
}
