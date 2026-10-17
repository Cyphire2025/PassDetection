"use client";

import Link from "next/link";
import { ROUTES } from "@/constants/routes";
import type { WhatsAppBroadcastSourceContacts } from "../api/whatsapp-source-groups.api";
import { useState } from "react";
import { Button, Input, Skeleton } from "@/components/ui";
import type {
  WhatsAppBroadcastGroupDetail,
  WhatsAppRejectedContact,
} from "../api/whatsapp.api";
import {
  useResolveWhatsAppRejectedContact,
  useRestoreWhatsAppReplacedRecipient,
  useWhatsAppRecipientRoster,
} from "../hooks/use-whatsapp";
import {
  DialogFrame,
  ErrorBanner,
  readErrorMessage,
} from "../components/whatsapp-dialog-ui";
import { EmptyWorkspace, tableClass } from "./workspace-ui";

export function RecipientExceptions({
  group,
  sourceContacts = [],
  search = "",
}: {
  group: WhatsAppBroadcastGroupDetail;
  sourceContacts?: WhatsAppBroadcastSourceContacts["contacts"];
  search?: string;
}) {
  const query = useWhatsAppRecipientRoster(group.id);
  const restore = useRestoreWhatsAppReplacedRecipient();
  const [correcting, setCorrecting] = useState<WhatsAppRejectedContact | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const items =
    query.data?.items
      .filter((item) => item.kind !== "recipient")
      .filter((item) => {
        const fields =
          item.kind === "rejected"
            ? [
                item.rejected_contact.raw_name,
                item.rejected_contact.raw_phone_number,
                ...Object.values(item.rejected_contact.imported_fields ?? {}),
              ]
            : item.kind === "replaced"
              ? [
                  item.replaced_recipient.name,
                  item.replaced_recipient.phone_number,
                ]
              : [item.unidentified_upload.name];
        return !search || fields.join(" ").toLocaleLowerCase().includes(search);
      }) ?? [];
  return (
    <>
      {query.isLoading ? (
        <Skeleton className="m-5 h-40" />
      ) : query.error ? (
        <div className="p-5">
          <ErrorBanner message="Contact issues could not be loaded." />
          <Button variant="ghost" onClick={() => void query.refetch()}>
            Try again
          </Button>
        </div>
      ) : items.length === 0 && sourceContacts.length === 0 ? (
        <EmptyWorkspace
          title={search ? "No matching contact issues" : "No contact issues"}
          description="Rejected imports, replaced recipients and unmatched submissions will appear here when they need attention."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead>
              <tr>
                <th>Contact</th>
                <th>Reason</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {sourceContacts.map((contact) => (
                <tr key={`source:${contact.source_submission_id}`}>
                  <td>
                    <p className="font-medium text-slate-900">
                      {contact.name || "Unnamed traveller"}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {contact.phone_number || "No WhatsApp number provided"}
                    </p>
                  </td>
                  <td className="text-xs text-slate-500">
                    {contact.issue === "missing_phone"
                      ? "WhatsApp number missing"
                      : contact.issue === "invalid_phone"
                        ? "WhatsApp number invalid"
                        : "Source contact needs correction"}
                  </td>
                  <td>
                    <Link
                      href={ROUTES.dashboard.passportGroup(
                        contact.source_group_id,
                      )}
                      className="text-xs font-medium text-blue-700"
                    >
                      Correct in source group
                    </Link>
                  </td>
                </tr>
              ))}
              {items.map((item) => {
                if (item.kind === "rejected")
                  return (
                    <tr key={item.rejected_contact.id}>
                      <td>
                        {item.rejected_contact.raw_name || "Unnamed contact"}
                        <p className="mt-1 text-xs text-slate-500">
                          {item.rejected_contact.raw_phone_number ||
                            "No number"}
                        </p>
                      </td>
                      <td className="text-xs text-slate-500">
                        {item.rejected_contact.reason}
                      </td>
                      <td>
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={group.is_archived}
                          onClick={() => setCorrecting(item.rejected_contact)}
                        >
                          Correct contact
                        </Button>
                      </td>
                    </tr>
                  );
                if (item.kind === "replaced") {
                  const person = item.replaced_recipient;
                  return (
                    <tr key={person.resolution_id}>
                      <td>{person.name || person.phone_number}</td>
                      <td className="text-xs text-slate-500">
                        Replaced by {person.replacement_name}
                      </td>
                      <td>
                        <Button
                          size="sm"
                          variant="secondary"
                          isLoading={restore.isPending}
                          disabled={group.is_archived}
                          onClick={async () => {
                            try {
                              await restore.mutateAsync({
                                broadcastGroupId: group.id,
                                clientGroupId: person.client_group_id,
                                resolutionId: person.resolution_id,
                              });
                            } catch (cause) {
                              setError(
                                readErrorMessage(
                                  cause,
                                  "Could not restore recipient.",
                                ),
                              );
                            }
                          }}
                        >
                          Restore recipient
                        </Button>
                      </td>
                    </tr>
                  );
                }
                if (item.kind === "unidentified")
                  return (
                    <tr key={item.unidentified_upload.submission_id}>
                      <td>{item.unidentified_upload.name}</td>
                      <td className="text-xs text-slate-500">
                        Submission has not been matched to an imported contact
                      </td>
                      <td>
                        <Link
                          className="text-xs font-medium text-blue-700"
                          href={`/passports/groups/${encodeURIComponent(item.unidentified_upload.client_group_id)}/whatsapp`}
                        >
                          Open matching
                        </Link>
                      </td>
                    </tr>
                  );
                return null;
              })}
            </tbody>
          </table>
        </div>
      )}
      {error && (
        <div className="p-5">
          <ErrorBanner message={error} />
        </div>
      )}
      {correcting && (
        <CorrectContact
          groupId={group.id}
          contact={correcting}
          onClose={() => setCorrecting(null)}
        />
      )}
    </>
  );
}

function CorrectContact({
  groupId,
  contact,
  onClose,
}: {
  groupId: string;
  contact: WhatsAppRejectedContact;
  onClose: () => void;
}) {
  const mutation = useResolveWhatsAppRejectedContact();
  const [confirmed, setConfirmed] = useState(false);
  return (
    <DialogFrame
      title="Correct imported contact"
      onClose={onClose}
      isBusy={mutation.isPending}
    >
      <form
        className="space-y-4"
        onSubmit={async (event) => {
          event.preventDefault();
          const values = new FormData(event.currentTarget);
          try {
            await mutation.mutateAsync({
              groupId,
              rejectedContactId: contact.id,
              name: String(values.get("name") ?? ""),
              phoneNumber: String(values.get("phone") ?? ""),
              recipientOptInConfirmed: confirmed,
            });
            onClose();
          } catch {
            /* error rendered below */
          }
        }}
      >
        <Input
          label="Name"
          name="name"
          defaultValue={contact.raw_name ?? ""}
          required
        />
        <Input
          label="WhatsApp number"
          name="phone"
          type="tel"
          defaultValue={contact.raw_phone_number ?? ""}
          required
        />
        <label className="flex gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          Recipient agreed to receive WhatsApp updates.
        </label>
        {mutation.error && (
          <ErrorBanner
            message={readErrorMessage(
              mutation.error,
              "Could not correct contact.",
            )}
          />
        )}
        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="secondary"
            onClick={onClose}
            disabled={mutation.isPending}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={!confirmed}
            isLoading={mutation.isPending}
          >
            Save contact
          </Button>
        </div>
      </form>
    </DialogFrame>
  );
}
