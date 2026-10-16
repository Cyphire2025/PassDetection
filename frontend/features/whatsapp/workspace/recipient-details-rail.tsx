"use client";

import { Pencil, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui";
import type {
  WhatsAppRecipient,
  WhatsAppRecipientDetailsEdit,
} from "../api/whatsapp.api";
import { useUpdateWhatsAppRecipientDetails } from "../hooks/use-whatsapp";
import type { WhatsAppBroadcastSourceContacts } from "../api/whatsapp-source-groups.api";
import { readErrorMessage } from "../components/whatsapp-dialog-ui";
import { fieldClass } from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";

export interface RecipientPerson {
  key: string;
  recipient: WhatsAppRecipient;
  name: string;
  fields: Record<string, string>;
  mergedId: string | null;
}
export function recipientPeople(
  recipients: WhatsAppRecipient[],
  contacts: WhatsAppBroadcastSourceContacts["contacts"] = [],
): RecipientPerson[] {
  const byRecipient = new Map<
    string,
    WhatsAppBroadcastSourceContacts["contacts"]
  >();
  for (const contact of contacts) {
    if (!contact.recipient_id) continue;
    const entries = byRecipient.get(contact.recipient_id) ?? [];
    entries.push(contact);
    byRecipient.set(contact.recipient_id, entries);
  }
  return recipients.flatMap((recipient) => {
    const sourcePeople = byRecipient.get(recipient.id) ?? [];
    if (sourcePeople.length)
      return sourcePeople.map((contact) => ({
        key: `${recipient.id}:source:${contact.source_submission_id}`,
        recipient: { ...recipient, is_source_managed: true },
        name: contact.name || "Unnamed recipient",
        fields: contact.imported_fields,
        mergedId: null,
      }));
    return [
      {
        key: recipient.id,
        recipient,
        name: recipient.name || "Unnamed recipient",
        fields: recipient.imported_fields,
        mergedId: null,
      },
      ...(recipient.merged_contacts ?? []).map((contact) => ({
        key: `${recipient.id}:${contact.id}`,
        recipient,
        name: contact.name || "Unnamed recipient",
        fields: contact.imported_fields,
        mergedId: contact.id,
      })),
    ];
  });
}
export function detailLabel(key: string) {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function RecipientDetailsRail({
  people,
  groupId,
  disabled,
  onClose,
}: {
  people: RecipientPerson[];
  groupId: string;
  disabled: boolean;
  onClose: (key: string) => void;
}) {
  return (
    <aside aria-label="Open recipient details" className={styles.detailRail}>
      <div className="flex flex-wrap items-center justify-between gap-2 px-1 text-xs text-slate-500">
        <span>{people.length} details open</span>
        <span>Open another to compare</span>
      </div>
      <div className={styles.detailStack} data-many={people.length > 2}>
        {people.map((person) => (
          <RecipientDetailCard
            key={person.key}
            person={person}
            groupId={groupId}
            disabled={disabled}
            onClose={() => onClose(person.key)}
          />
        ))}
      </div>
    </aside>
  );
}

function RecipientDetailCard({
  person,
  groupId,
  disabled,
  onClose,
}: {
  person: RecipientPerson;
  groupId: string;
  disabled: boolean;
  onClose: () => void;
}) {
  const mutation = useUpdateWhatsAppRecipientDetails();
  const [draft, setDraft] = useState<WhatsAppRecipientDetailsEdit | null>(null);
  const entries = Object.entries(person.fields).filter(
    ([key]) => key !== "duplicate_conflicting_fields",
  );
  return (
    <section
      aria-label={`Details for ${person.name}`}
      className={`${styles.surface} ${styles.enter} ${styles.detailCard}`}
    >
      <header className="flex shrink-0 items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="min-w-0">
          <h3 className="break-words text-sm font-semibold text-slate-900">
            {person.name}
          </h3>
          <p className="mt-1 text-xs text-slate-500">
            {person.recipient.normalized_phone_number}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Close details for ${person.name}`}
          onClick={onClose}
          disabled={mutation.isPending}
        >
          <X className="h-4 w-4" />
        </Button>
      </header>
      <div
        className={`${styles.detailBody} space-y-4 focus-visible:outline-blue-500`}
        role="region"
        aria-label={`Detail fields for ${person.name}`}
        tabIndex={0}
      >
        {person.recipient.is_source_managed && (
          <p className="text-xs leading-5 text-slate-500">
            These details are maintained in the linked source group.
          </p>
        )}
        {draft ? (
          <form
            className="space-y-3"
            onSubmit={async (event) => {
              event.preventDefault();
              try {
                await mutation.mutateAsync({
                  groupId,
                  recipientId: person.recipient.id,
                  details: draft,
                });
                setDraft(null);
              } catch {
                /* visible below */
              }
            }}
          >
            <label className="block text-xs font-medium text-slate-600">
              Name
              <input
                value={draft.name}
                required
                maxLength={100}
                onChange={(event) =>
                  setDraft({ ...draft, name: event.target.value })
                }
                className={`mt-1 ${fieldClass}`}
              />
            </label>
            {Object.entries(draft.imported_fields).map(([key, value]) => (
              <label
                key={key}
                className="block text-xs font-medium text-slate-600"
              >
                {detailLabel(key)}
                <input
                  value={value}
                  maxLength={256}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      imported_fields: {
                        ...draft.imported_fields,
                        [key]: event.target.value,
                      },
                    })
                  }
                  className={`mt-1 ${fieldClass}`}
                />
              </label>
            ))}
            {mutation.error && (
              <p role="alert" className="text-xs text-red-600">
                {readErrorMessage(mutation.error, "Could not save details.")}
              </p>
            )}
            <div className="flex gap-2">
              <Button type="submit" size="sm" isLoading={mutation.isPending}>
                Save details
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={mutation.isPending}
                onClick={() => setDraft(null)}
              >
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <>
            <dl className="space-y-3">
              {entries.map(([key, value]) => (
                <div key={key}>
                  <dt className="text-xs text-slate-500">{detailLabel(key)}</dt>
                  <dd className="mt-1 break-words text-sm text-slate-800">
                    {value || "—"}
                  </dd>
                </div>
              ))}
            </dl>
            {entries.length === 0 && (
              <p className="text-sm text-slate-500">
                No additional details were imported.
              </p>
            )}
            {!disabled && !person.recipient.is_source_managed && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  mutation.reset();
                  setDraft({
                    merged_contact_id: person.mergedId,
                    expected_name: person.mergedId
                      ? (person.recipient.merged_contacts?.find(
                          (contact) => contact.id === person.mergedId,
                        )?.name ?? null)
                      : person.recipient.name,
                    expected_imported_fields: { ...person.fields },
                    name: person.name,
                    imported_fields: Object.fromEntries(
                      entries.filter(
                        ([key]) => !["name", "phone_number"].includes(key),
                      ),
                    ),
                  });
                }}
              >
                <Pencil className="h-3.5 w-3.5" />
                Edit details
              </Button>
            )}
          </>
        )}
      </div>
    </section>
  );
}
