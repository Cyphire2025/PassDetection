"use client";

import { useDeferredValue, useState } from "react";
import { clampPageOffset } from "@/lib/utils/pagination";
import type { ComposerController } from "./message-composer";
import {
  EmptyWorkspace,
  tableClass,
  WorkspacePagination,
  WorkspaceSearch,
} from "./workspace-ui";
import { ComposerAudienceFilters } from "./message-composer-audience-filters";
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
  const pageOffset = clampPageOffset(offset, matches.length, 25);
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
        <ComposerAudienceFilters model={model} changeFilter={changeFilter} />
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
              {matches.slice(pageOffset, pageOffset + 25).map((recipient) => (
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
        offset={pageOffset}
        limit={25}
        onChange={setOffset}
        label="Send recipients"
        busy={model.pending}
      />
    </section>
  );
}
