"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import { Button, ConfirmDialog } from "@/components/ui";
import { useDeleteWhatsAppRecipient } from "../hooks/use-whatsapp";
import { ErrorBanner, readErrorMessage } from "../components/whatsapp-dialog-ui";
import { AddRecipientsDialog } from "./add-recipients-dialog";
import { useBroadcast } from "./broadcast-workspace-shell";
import { RecipientDetailsRail } from "./recipient-details-rail";
import type { RecipientPerson } from "./recipient-roster-model";
import { EmptyWorkspace } from "./workspace-ui";
import { RecipientExceptions } from "./recipient-exceptions";
import { RecipientRosterFilters } from "./recipient-roster-filters";
import { RecipientRosterTable } from "./recipient-roster-table";
import { useRecipientRoster } from "./use-recipient-roster";
import styles from "./broadcast-workspace.module.css";

export function BroadcastRecipientsPage() {
  const group = useBroadcast();
  const remove = useDeleteWhatsAppRecipient();
  const roster = useRecipientRoster(group);
  const { filter, deferred, sourceIssues, sources, displayed, details, setOpenDetails } = roster;
  const [adding, setAdding] = useState(false);
  const [editingPhone, setEditingPhone] = useState<string | null>(null);
  const [removing, setRemoving] = useState<RecipientPerson | null>(null);
  const [error, setError] = useState<string | null>(null);
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
        className={`grid items-start gap-6 ${details.length ? styles.withDetails : ""}`}
      >
        <section className={styles.surface}>
          <div className="space-y-4 p-5">
            <RecipientRosterFilters roster={roster} group={group} />
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
            <RecipientRosterTable
              roster={roster}
              group={group}
              editingPhone={editingPhone}
              setEditingPhone={setEditingPhone}
              setRemoving={setRemoving}
            />
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
