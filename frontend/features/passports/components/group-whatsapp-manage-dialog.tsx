"use client";

import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { X } from "lucide-react";
import { useId, useState, useRef } from "react";
import { Button, ConfirmDialog } from "@/components/ui";
import type { LinkedWhatsAppBroadcast } from "../api/upload-links.api";
import { useUpdateGroupWhatsAppLinks } from "../hooks/use-upload-links";
import { WhatsAppBroadcastSelector } from "./whatsapp-broadcast-selector";

export function ManageBroadcastsDialog({
  groupId,
  initialBroadcasts,
  onClose,
}: {
  groupId: string;
  initialBroadcasts: LinkedWhatsAppBroadcast[];
  onClose: () => void;
}) {
  const titleId = useId();
  const initialIds = initialBroadcasts.map((broadcast) => broadcast.id);
  const [selectedIds, setSelectedIds] = useState<string[]>(() => [...initialIds]);
  const [selectedMatchingFields, setSelectedMatchingFields] = useState<Record<string, string[]>>(
    () => Object.fromEntries(
      initialBroadcasts.flatMap((broadcast) => (
        broadcast.matching_field_keys && broadcast.matching_field_keys.length > 0
          ? [[broadcast.id, [...broadcast.matching_field_keys]]]
          : []
      )),
    ),
  );
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmUnlinkAll, setConfirmUnlinkAll] = useState(false);
  const updateLinks = useUpdateGroupWhatsAppLinks(groupId);

  const dialogRef = useRef<HTMLDivElement>(null);
  const handleDialogKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !updateLinks.isPending, onClose });

  const saveLinks = () => {
    setSaveError(null);
    const matchingFieldsByBroadcast = Object.fromEntries(
      selectedIds.flatMap((broadcastId) => {
        const fields = selectedMatchingFields[broadcastId];
        return fields && fields.length > 0
          ? [[broadcastId, fields]]
          : [];
      }),
    );
    updateLinks.mutate({
      whatsappBroadcastGroupIds: selectedIds,
      matchingFieldsByBroadcast,
    }, {
      onSuccess: onClose,
      onError: () => setSaveError(
        "The WhatsApp broadcasts could not be linked. Try again.",
      ),
    });
  };

  return (
    <>
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm">
        <div
          ref={dialogRef}
          onKeyDown={handleDialogKeyDown}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          aria-busy={updateLinks.isPending}
          className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        >
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4 sm:px-6">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-slate-900">
              Link WhatsApp broadcasts
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              Select every broadcast whose recipients should be compared with this passport group.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close WhatsApp broadcast linking dialog"
            onClick={onClose}
            disabled={updateLinks.isPending}
            className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div className="overflow-y-auto p-4 sm:p-6">
          <WhatsAppBroadcastSelector
            selectedIds={selectedIds}
            onChange={setSelectedIds}
            selectedMatchingFields={selectedMatchingFields}
            onMatchingFieldsChange={setSelectedMatchingFields}
            disabled={updateLinks.isPending}
            groupId={groupId}
          />
          {saveError && (
            <div role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {saveError}
            </div>
          )}
        </div>

          <div className="flex flex-wrap justify-end gap-3 border-t border-slate-200 px-5 py-4 sm:px-6">
            <Button type="button" variant="secondary" onClick={onClose} disabled={updateLinks.isPending}>
              Cancel
            </Button>
            <Button
              type="button"
              isLoading={updateLinks.isPending}
              disabled={updateLinks.isPending}
              onClick={() => {
                if (initialIds.length > 0 && selectedIds.length === 0) {
                  setConfirmUnlinkAll(true);
                  return;
                }
                saveLinks();
              }}
            >
              Save linked broadcasts
            </Button>
          </div>
        </div>
      </div>
      <ConfirmDialog
        isOpen={confirmUnlinkAll}
        title="Unlink every WhatsApp broadcast?"
        description="Recipient submission tracking will be removed from this group until a broadcast is linked again. The broadcasts and passport submissions will not be deleted."
        confirmLabel="Unlink all broadcasts"
        variant="danger"
        isLoading={updateLinks.isPending}
        onClose={() => setConfirmUnlinkAll(false)}
        onConfirm={() => {
          setConfirmUnlinkAll(false);
          saveLinks();
        }}
      />
    </>
  );
}
