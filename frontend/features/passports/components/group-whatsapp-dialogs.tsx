"use client";

import { useModalKeyboardBoundary } from "@/components/ui/modal";

import { CheckCircle2, Loader2, Search, X } from "lucide-react";
import { useId, useState, useRef } from "react";
import { Button, ConfirmDialog, Input } from "@/components/ui";
import type { GroupWhatsAppMatch, LinkedWhatsAppBroadcast } from "../api/upload-links.api";
import { useReplacementCandidates, useResolveUnidentifiedReplacement, useUpdateGroupWhatsAppLinks } from "../hooks/use-upload-links";
import { WhatsAppBroadcastSelector } from "./whatsapp-broadcast-selector";
import { rowPrimaryName, submissionPrimaryPhone, fieldLabel, replacementCandidateSearchText, createRosterRequestId } from "./group-whatsapp-tracking-model";
import { SubmissionDetailsList } from "./group-whatsapp-tracking-table";

export function ReplacementDialog({
  groupId,
  row,
  onClose,
  onResolved,
}: {
  groupId: string;
  row: GroupWhatsAppMatch;
  onClose: () => void;
  onResolved: () => void;
}) {
  const titleId = useId();
  const [search, setSearch] = useState("");
  const [requestId] = useState(createRosterRequestId);
  const [selectedRecipientId, setSelectedRecipientId] = useState<string | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const candidatesQuery = useReplacementCandidates(groupId);
  const resolveReplacement = useResolveUnidentifiedReplacement(groupId);
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const candidates = (candidatesQuery.data?.items ?? []).filter((candidate) => (
    !normalizedSearch || replacementCandidateSearchText(candidate).includes(
      normalizedSearch,
    )
  ));
  const selectedCandidate = candidatesQuery.data?.items.find(
    (candidate) => candidate.recipient_id === selectedRecipientId,
  );

  const dialogRef = useRef<HTMLDivElement>(null);
  const handleDialogKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !resolveReplacement.isPending, onClose });

  const confirmReplacement = () => {
    const submissionId = row.submission_ids[0];
    if (!submissionId || !selectedRecipientId) return;
    setError(null);
    resolveReplacement.mutate(
      {
        submissionId,
        recipientId: selectedRecipientId,
        requestId,
      },
      {
        onSuccess: onResolved,
        onError: () => setError(
          "The replacement could not be saved. The recipient may have changed; refresh and try again.",
        ),
      },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm">
      <div
        ref={dialogRef}
        onKeyDown={handleDialogKeyDown}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-busy={resolveReplacement.isPending}
        className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4 sm:px-6">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-slate-900">
              Mark as a replacement
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              Choose the person from the current WhatsApp broadcast who is no
              longer going. Future messages to that original recipient will stop.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close replacement dialog"
            onClick={onClose}
            disabled={resolveReplacement.isPending}
            className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5 sm:p-6">
          <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">
              New person going
            </div>
            <div className="mt-1 font-semibold text-slate-900">
              {rowPrimaryName(row)}
            </div>
            <div className="mt-1 text-sm text-slate-600">
              {submissionPrimaryPhone(row) || "No submitted phone number"}
            </div>
            <SubmissionDetailsList
              details={row.submission_details}
              className="mt-3"
            />
          </div>

          <div className="space-y-3">
            <Input
              label="Find the original recipient"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search name, phone number, broadcast, or imported detail"
              leftAddon={<Search className="h-4 w-4" aria-hidden="true" />}
              autoFocus
              disabled={resolveReplacement.isPending}
            />

            {candidatesQuery.isLoading ? (
              <div className="flex items-center justify-center gap-2 rounded-xl border border-slate-200 py-10 text-sm text-slate-500">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Loading current broadcast recipients
              </div>
            ) : candidatesQuery.error ? (
              <div
                role="alert"
                className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
              >
                Current recipients could not be loaded. Close this box and try
                again.
              </div>
            ) : candidates.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center">
                <div className="font-medium text-slate-700">
                  {normalizedSearch
                    ? "No recipient matches this search"
                    : "No active recipient is available to replace"}
                </div>
                <p className="mt-1 text-sm text-slate-500">
                  {normalizedSearch
                    ? "Try a name, phone number, or broadcast name."
                    : "Every linked recipient may already be inactive or replaced."}
                </p>
              </div>
            ) : (
              <div
                role="radiogroup"
                aria-label="Choose the original broadcast recipient"
                className="space-y-2"
              >
                {candidates.map((candidate) => {
                  const isSelected = (
                    candidate.recipient_id === selectedRecipientId
                  );
                  const details = Object.entries(candidate.imported_fields)
                    .filter(([, value]) => value.trim());
                  return (
                    <div
                      key={candidate.recipient_id}
                      className={`overflow-hidden rounded-xl border transition ${
                        isSelected
                          ? "border-blue-500 bg-blue-50 ring-2 ring-blue-100"
                          : "border-slate-200 bg-white hover:border-slate-300"
                      }`}
                    >
                      <button
                        type="button"
                        role="radio"
                        aria-checked={isSelected}
                        disabled={resolveReplacement.isPending}
                        onClick={() => {
                          setSelectedRecipientId(candidate.recipient_id);
                          setError(null);
                        }}
                        className="flex w-full items-start gap-3 p-4 text-left disabled:opacity-60"
                      >
                        <span
                          className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${
                            isSelected
                              ? "border-blue-600 bg-blue-600 text-white"
                              : "border-slate-300 bg-white"
                          }`}
                        >
                          {isSelected && (
                            <CheckCircle2
                              className="h-3.5 w-3.5"
                              aria-hidden="true"
                            />
                          )}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block font-semibold text-slate-900">
                            {candidate.name?.trim() || "Unnamed recipient"}
                          </span>
                          <span className="mt-0.5 block text-sm text-slate-600">
                            {candidate.phone}
                          </span>
                          <span className="mt-2 flex flex-wrap gap-1.5">
                            {candidate.broadcast_names.map((name) => (
                              <span
                                key={name}
                                className="rounded-full bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-800"
                              >
                                {name}
                              </span>
                            ))}
                          </span>
                        </span>
                      </button>
                      {details.length > 0 && (
                        <details className="border-t border-slate-100 px-4 py-3">
                          <summary className="cursor-pointer text-xs font-semibold text-blue-700">
                            View imported details
                          </summary>
                          <dl className="mt-3 grid gap-2 sm:grid-cols-2">
                            {details.map(([key, value]) => (
                              <div key={key} className="min-w-0">
                                <dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                                  {fieldLabel(key)}
                                </dt>
                                <dd className="break-words text-xs text-slate-700">
                                  {value}
                                </dd>
                              </div>
                            ))}
                          </dl>
                        </details>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {selectedCandidate && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900">
              <strong>{selectedCandidate.name || selectedCandidate.phone}</strong>{" "}
              will be recorded as the original person who opted out. The new
              upload will remain active as their replacement.
            </div>
          )}
          {error && (
            <div
              role="alert"
              className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            >
              {error}
            </div>
          )}
        </div>

        <div className="flex flex-wrap justify-end gap-3 border-t border-slate-200 px-5 py-4 sm:px-6">
          <Button
            type="button"
            variant="secondary"
            onClick={onClose}
            disabled={resolveReplacement.isPending}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={confirmReplacement}
            isLoading={resolveReplacement.isPending}
            disabled={
              !selectedRecipientId
              || !row.submission_ids[0]
              || candidatesQuery.isLoading
              || Boolean(candidatesQuery.error)
            }
          >
            Confirm replacement
          </Button>
        </div>
      </div>
    </div>
  );
}

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
