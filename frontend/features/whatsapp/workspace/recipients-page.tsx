"use client";

import { Eye, Pencil, Plus, Trash2 } from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";
import { Button, ConfirmDialog } from "@/components/ui";
import { useDeleteWhatsAppRecipient } from "../hooks/use-whatsapp";
import { useWhatsAppBroadcastSourceContacts } from "../hooks/use-whatsapp-source-groups";
import { getMessageStatus } from "../utils/recipient-delivery";
import {
  ErrorBanner,
  readErrorMessage,
} from "../components/whatsapp-dialog-ui";
import { AddRecipientsDialog } from "./add-recipients-dialog";
import { useBroadcast } from "./broadcast-workspace-shell";
import {
  RecipientDetailsRail,
  recipientPeople,
  type RecipientPerson,
} from "./recipient-details-rail";
import { RecipientPhoneCell, RecipientRowMenu } from "./recipient-controls";
import {
  DeliveryBadge,
  EmptyWorkspace,
  fieldClass,
  tableClass,
  WorkspacePagination,
  WorkspaceSearch,
} from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";
import { RecipientExceptions } from "./recipient-exceptions";

function welcomeStatus(person: RecipientPerson) {
  const saved = getMessageStatus(person.recipient, "welcome");
  return (
    saved?.latest_resend_status ??
    saved?.status ??
    person.recipient.welcome_status ??
    "not_sent"
  );
}

export function BroadcastRecipientsPage() {
  const group = useBroadcast();
  const remove = useDeleteWhatsAppRecipient();
  const [search, setSearch] = useState("");
  const deferred = useDeferredValue(search).trim().toLocaleLowerCase();
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("asc");
  const [offset, setOffset] = useState(0);
  const [adding, setAdding] = useState(false);
  const [openDetails, setOpenDetails] = useState<string[]>([]);
  const [editingPhone, setEditingPhone] = useState<string | null>(null);
  const [removing, setRemoving] = useState<RecipientPerson | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sources = useWhatsAppBroadcastSourceContacts(
    group.id,
    Boolean(group.source_contact_count || group.has_import_only_source),
  );
  const people = useMemo(
    () => recipientPeople(group.recipients, sources.data?.contacts),
    [group.recipients, sources.data?.contacts],
  );
  const failedCount = people.filter(
    (person) => welcomeStatus(person) === "failed",
  ).length;
  const sourceIssues =
    sources.data?.contacts.filter((contact) => !contact.recipient_id) ?? [];
  const displayed = useMemo(() => {
    const result = people.filter(
      (person) =>
        (filter !== "failed" || welcomeStatus(person) === "failed") &&
        (filter !== "not_sent" || welcomeStatus(person) === "not_sent") &&
        (!deferred ||
          [
            person.name,
            person.recipient.normalized_phone_number,
            ...Object.values(person.fields),
          ].some((value) => value.toLocaleLowerCase().includes(deferred))),
    );
    return sort === "import"
      ? result
      : result.sort(
          (a, b) =>
            a.name.localeCompare(b.name, "en", {
              sensitivity: "base",
              numeric: true,
            }) * (sort === "desc" ? -1 : 1),
        );
  }, [people, filter, deferred, sort]);
  const pageOffset = Math.min(
    offset,
    Math.max(0, Math.ceil(displayed.length / 50) - 1) * 50,
  );
  const details = openDetails.flatMap((key) => {
    const person = people.find((item) => item.key === key);
    return person ? [person] : [];
  });
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Recipients</h2>
          <p className="mt-1 text-sm text-slate-500">
            Find people, correct their WhatsApp numbers and compare imported
            details.
          </p>
        </div>
        <Button disabled={group.is_archived} onClick={() => setAdding(true)}>
          <Plus className="h-4 w-4" />
          Add recipients
        </Button>
      </div>
      <div
        className={`grid items-start gap-5 ${details.length ? "xl:grid-cols-[minmax(0,1fr)_330px]" : ""}`}
      >
        <section className={styles.surface}>
          <div className="space-y-4 p-5">
            <WorkspaceSearch
              value={search}
              onChange={(value) => {
                setSearch(value);
                setOffset(0);
              }}
              label="Search recipients"
              placeholder="Search name, number or imported details…"
            >
              <label className="text-xs text-slate-500">
                <span className="sr-only">Sort recipients</span>
                <select
                  aria-label="Sort recipients"
                  disabled={filter === "issues"}
                  value={sort}
                  onChange={(event) => {
                    setSort(event.target.value);
                    setOffset(0);
                  }}
                  className={`${fieldClass} w-auto`}
                >
                  <option value="asc">Name A–Z</option>
                  <option value="desc">Name Z–A</option>
                  <option value="import">Import order</option>
                </select>
              </label>
            </WorkspaceSearch>
            <div className="flex flex-wrap gap-2">
              {[
                { id: "all", label: "All recipients", count: people.length },
                { id: "failed", label: "Welcome failed", count: failedCount },
                {
                  id: "not_sent",
                  label: "Welcome not sent",
                  count: people.filter(
                    (person) => welcomeStatus(person) === "not_sent",
                  ).length,
                },
                {
                  id: "issues",
                  label: "Contact issues",
                  count: group.rejected_contact_count + sourceIssues.length,
                },
              ].map((item) => (
                <button
                  key={item.id}
                  onClick={() => {
                    setFilter(item.id);
                    setOffset(0);
                  }}
                  aria-pressed={filter === item.id}
                  aria-label={`${item.label} (${item.count})`}
                  className={`rounded-lg px-3 py-2 text-xs font-medium transition-colors ${filter === item.id ? "bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-200" : "bg-slate-50 text-slate-600 hover:bg-slate-100"}`}
                >
                  {item.label}
                  <span className="ml-2 tabular-nums opacity-70">
                    {item.count.toLocaleString()}
                  </span>
                </button>
              ))}
            </div>
            {filter === "failed" && (
              <p className="text-xs leading-5 text-slate-500">
                These welcome sends failed. Correct a number here; Delivery
                history shows the recorded reason for each send.
              </p>
            )}
            {error && <ErrorBanner message={error} />}
            {sources.error && (
              <ErrorBanner message="Linked contact details could not be loaded. Refresh this page before comparing source travellers." />
            )}
          </div>
          {filter === "issues" ? (
            <RecipientExceptions
              group={group}
              sourceContacts={sourceIssues.filter(
                (contact) =>
                  !deferred ||
                  `${contact.name} ${contact.phone_number}`
                    .toLocaleLowerCase()
                    .includes(deferred),
              )}
              search={deferred}
            />
          ) : displayed.length === 0 ? (
            <EmptyWorkspace
              title="No matching recipients"
              description="Try another search or change the recipient filter."
            />
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className={tableClass}>
                  <thead>
                    <tr>
                      <th>Recipient</th>
                      <th>WhatsApp number</th>
                      <th>Welcome status</th>
                      <th>
                        <span className="sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayed
                      .slice(pageOffset, pageOffset + 50)
                      .map((person) => (
                        <tr
                          key={person.key}
                          className={
                            openDetails.includes(person.key)
                              ? "bg-blue-50/40"
                              : ""
                          }
                        >
                          <td>
                            <p className="font-medium text-slate-900">
                              {person.name}
                            </p>
                            {person.mergedId && (
                              <p className="mt-1 text-xs text-slate-400">
                                Shared WhatsApp number
                              </p>
                            )}
                          </td>
                          <td>
                            <RecipientPhoneCell
                              groupId={group.id}
                              recipientId={person.recipient.id}
                              number={person.recipient.normalized_phone_number}
                              editing={editingPhone === person.key}
                              disabled={group.is_archived}
                              onEdit={() => setEditingPhone(person.key)}
                              onDone={() => setEditingPhone(null)}
                            />
                          </td>
                          <td>
                            <DeliveryBadge status={welcomeStatus(person)} />
                          </td>
                          <td className="text-right">
                            <RecipientRowMenu name={person.name}>
                              {(close) => (
                                <>
                                  <button
                                    role="menuitem"
                                    onClick={() => {
                                      setOpenDetails((current) =>
                                        current.includes(person.key)
                                          ? current
                                          : [...current, person.key],
                                      );
                                      close();
                                    }}
                                  >
                                    <Eye className="h-3.5 w-3.5" />
                                    View details
                                  </button>
                                  {!group.is_archived && (
                                    <>
                                      <button
                                        role="menuitem"
                                        onClick={() => {
                                          setEditingPhone(person.key);
                                          close();
                                        }}
                                      >
                                        <Pencil className="h-3.5 w-3.5" />
                                        Edit WhatsApp number
                                      </button>
                                      <div className="my-1 border-t border-slate-100" />
                                      <button
                                        role="menuitem"
                                        className="text-red-600 disabled:opacity-40"
                                        disabled={group.recipients.length <= 1}
                                        onClick={() => {
                                          setRemoving(person);
                                          close();
                                        }}
                                      >
                                        <Trash2 className="h-3.5 w-3.5" />
                                        Remove recipient
                                      </button>
                                    </>
                                  )}
                                </>
                              )}
                            </RecipientRowMenu>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              <WorkspacePagination
                total={displayed.length}
                offset={pageOffset}
                limit={50}
                onChange={setOffset}
                label="Recipients"
              />
            </>
          )}
        </section>
        {details.length > 0 && (
          <RecipientDetailsRail
            people={details}
            groupId={group.id}
            disabled={Boolean(group.is_archived)}
            onClose={(key) =>
              setOpenDetails((current) =>
                current.filter((item) => item !== key),
              )
            }
          />
        )}
      </div>
      {adding && <AddRecipientsDialog onClose={() => setAdding(false)} />}
      <ConfirmDialog
        isOpen={Boolean(removing)}
        title="Remove recipient?"
        description={`Remove ${removing?.name ?? "this recipient"} from this broadcast?${removing?.recipient.merged_contacts?.length ? " Other contacts sharing this delivery number will also be removed from the broadcast." : ""}`}
        confirmLabel="Remove recipient"
        variant="danger"
        isLoading={remove.isPending}
        onClose={() => setRemoving(null)}
        onConfirm={async () => {
          if (!removing) return;
          try {
            await remove.mutateAsync({
              groupId: group.id,
              recipientId: removing.recipient.id,
            });
            setRemoving(null);
          } catch (cause) {
            setError(readErrorMessage(cause, "Could not remove recipient."));
            setRemoving(null);
          }
        }}
      />
    </div>
  );
}
