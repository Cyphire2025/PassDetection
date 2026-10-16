"use client";

import { ROUTES } from "@/constants/routes";
import { Archive, Plus, RotateCcw, Trash2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, ConfirmDialog, Input } from "@/components/ui";
import type { WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";
import {
  useArchiveWhatsAppGroup,
  useDeleteWhatsAppGroup,
  useRestoreWhatsAppGroup,
  useUpdateWhatsAppGroup,
} from "../hooks/use-whatsapp";
import {
  ErrorBanner,
  readErrorMessage,
} from "../components/whatsapp-dialog-ui";
import { useBroadcast } from "./broadcast-workspace-shell";
import { workspaceDate } from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";

export function BroadcastDetailsPage() {
  const group = useBroadcast();
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">
          Broadcast details
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          Manage the name, support contacts and broadcast lifecycle.
        </p>
      </div>
      <BroadcastDetailsForm key={group.id} group={group} />
      <BroadcastLifecycle group={group} />
    </div>
  );
}

function BroadcastDetailsForm({
  group,
}: {
  group: WhatsAppBroadcastGroupDetail;
}) {
  const mutation = useUpdateWhatsAppGroup();
  const [name, setName] = useState(group.name);
  const [contacts, setContacts] = useState(
    group.support_contacts.map((contact) => ({
      name: contact.name,
      phone_number: contact.phone_number,
    })),
  );
  const [saved, setSaved] = useState(false);
  const dirty =
    name.trim() !== group.name ||
    JSON.stringify(contacts) !==
      JSON.stringify(
        group.support_contacts.map((contact) => ({
          name: contact.name,
          phone_number: contact.phone_number,
        })),
      );
  return (
    <form
      className={`${styles.surface} max-w-4xl space-y-6 p-5 sm:p-7`}
      onSubmit={async (event) => {
        event.preventDefault();
        if (!dirty || mutation.isPending) return;
        try {
          await mutation.mutateAsync({
            groupId: group.id,
            name: name.trim(),
            supportContacts: contacts,
          });
          setSaved(true);
        } catch {
          /* error rendered below */
        }
      }}
    >
      <fieldset
        disabled={group.is_archived || mutation.isPending}
        className="space-y-6"
      >
        <div className="max-w-lg">
          <Input
            label="Broadcast name"
            value={name}
            maxLength={100}
            required
            onChange={(event) => {
              setName(event.target.value);
              setSaved(false);
            }}
            hint="Used in trip messages that include the broadcast name."
          />
        </div>
        <div className="border-t border-slate-100 pt-5">
          <h3 className="text-sm font-semibold text-slate-900">
            Support contacts
          </h3>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            Choose one of these contacts when composing a passport-link message.
          </p>
          <div className="mt-4 space-y-3">
            {contacts.map((contact, index) => (
              <div
                key={index}
                className="grid items-end gap-3 sm:grid-cols-[1fr_1fr_auto]"
              >
                <Input
                  label={`Contact ${index + 1} name`}
                  required
                  value={contact.name}
                  onChange={(event) => {
                    setContacts((current) =>
                      current.map((item, position) =>
                        index === position
                          ? { ...item, name: event.target.value }
                          : item,
                      ),
                    );
                    setSaved(false);
                  }}
                />
                <Input
                  label="WhatsApp number"
                  type="tel"
                  required
                  value={contact.phone_number}
                  onChange={(event) => {
                    setContacts((current) =>
                      current.map((item, position) =>
                        index === position
                          ? { ...item, phone_number: event.target.value }
                          : item,
                      ),
                    );
                    setSaved(false);
                  }}
                />
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  disabled={contacts.length <= 1}
                  aria-label={`Remove support contact ${index + 1}`}
                  onClick={() => {
                    setContacts((current) =>
                      current.filter((_, position) => index !== position),
                    );
                    setSaved(false);
                  }}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
          <Button
            type="button"
            variant="ghost"
            className="mt-3"
            disabled={contacts.length >= 3}
            onClick={() => {
              setContacts((current) => [
                ...current,
                { name: "", phone_number: "" },
              ]);
              setSaved(false);
            }}
          >
            <Plus className="h-3.5 w-3.5" />
            Add support contact
          </Button>
        </div>
      </fieldset>
      {mutation.error && (
        <ErrorBanner
          message={readErrorMessage(
            mutation.error,
            "Could not save broadcast details.",
          )}
        />
      )}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
        <span role="status" className="text-xs text-slate-500">
          {saved && !dirty
            ? "Changes saved."
            : `Created ${workspaceDate(group.created_at)}`}
        </span>
        <Button
          type="submit"
          disabled={!dirty || group.is_archived || !contacts.length}
          isLoading={mutation.isPending}
        >
          Save changes
        </Button>
      </div>
    </form>
  );
}

function BroadcastLifecycle({
  group,
}: {
  group: WhatsAppBroadcastGroupDetail;
}) {
  const archive = useArchiveWhatsAppGroup(),
    restore = useRestoreWhatsAppGroup(),
    remove = useDeleteWhatsAppGroup();
  const router = useRouter();
  const [confirm, setConfirm] = useState<"archive" | "delete" | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <section className={`${styles.surface} max-w-4xl p-5 sm:p-7`}>
      <h3 className="text-sm font-semibold text-slate-900">
        Broadcast management
      </h3>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
        <p className="max-w-xl text-xs leading-5 text-slate-500">
          {group.is_archived
            ? "Restore this broadcast to edit recipients and send messages again."
            : "Archive this broadcast when the trip is complete. Its recipients and delivery history are retained."}
        </p>
        {group.is_archived ? (
          <Button
            variant="secondary"
            isLoading={restore.isPending}
            onClick={async () => {
              try {
                await restore.mutateAsync(group.id);
              } catch (cause) {
                setError(
                  readErrorMessage(cause, "Could not restore broadcast."),
                );
              }
            }}
          >
            <RotateCcw className="h-4 w-4" />
            Restore broadcast
          </Button>
        ) : (
          <Button variant="secondary" onClick={() => setConfirm("archive")}>
            <Archive className="h-4 w-4" />
            Archive broadcast
          </Button>
        )}
      </div>
      {group.is_archived && (
        <div className="mt-5 flex items-center justify-between gap-3 border-t border-slate-100 pt-5">
          <p className="text-xs text-slate-500">
            Permanently remove this broadcast and its retained data.
          </p>
          <Button
            variant="ghost"
            className="text-red-600"
            onClick={() => setConfirm("delete")}
          >
            <Trash2 className="h-4 w-4" />
            Delete broadcast
          </Button>
        </div>
      )}
      {error && (
        <div className="mt-4">
          <ErrorBanner message={error} />
        </div>
      )}
      <ConfirmDialog
        isOpen={confirm !== null}
        title={
          confirm === "delete"
            ? "Permanently delete broadcast?"
            : "Archive broadcast?"
        }
        description={
          confirm === "delete"
            ? "The broadcast, recipients and delivery history will be permanently deleted. This cannot be undone."
            : "This broadcast will become read-only. You can restore it later. In-progress or unconfirmed sends must be resolved first."
        }
        confirmLabel={
          confirm === "delete" ? "Delete broadcast" : "Archive broadcast"
        }
        variant={confirm === "delete" ? "danger" : "primary"}
        isLoading={archive.isPending || remove.isPending}
        onClose={() => setConfirm(null)}
        onConfirm={async () => {
          try {
            if (confirm === "delete") {
              await remove.mutateAsync(group.id);
              router.push(ROUTES.dashboard.whatsapp);
            } else await archive.mutateAsync(group.id);
            setConfirm(null);
          } catch (cause) {
            setError(
              readErrorMessage(cause, "The broadcast could not be updated."),
            );
            setConfirm(null);
          }
        }}
      />
    </section>
  );
}
