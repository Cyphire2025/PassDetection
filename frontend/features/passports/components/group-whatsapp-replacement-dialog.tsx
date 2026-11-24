"use client";

import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { Loader2, Search, X } from "lucide-react";
import { useId, useState, useRef } from "react";
import { Button, Input } from "@/components/ui";
import type { GroupWhatsAppMatch } from "../api/upload-links.api";
import { useReplacementCandidates, useResolveUnidentifiedReplacement } from "../hooks/use-upload-links";
import {
  rowPrimaryName,
  submissionPrimaryPhone,
  replacementCandidateSearchText,
  createRosterRequestId,
} from "./group-whatsapp-tracking-model";
import { SubmissionDetailsList } from "./group-whatsapp-tracking-table";
import { ReplacementRecipientChoice } from "./replacement-recipient-choice";

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
    if (!submissionId || !selectedRecipientId || !selectedCandidate) return;
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
                {candidates.map((candidate) => (
                  <ReplacementRecipientChoice
                    key={candidate.recipient_id}
                    candidate={candidate}
                    isSelected={candidate.recipient_id === selectedRecipientId}
                    disabled={resolveReplacement.isPending}
                    groupName={`${titleId}-recipient`}
                    onSelect={(recipientId) => {
                      setSelectedRecipientId(recipientId);
                      setError(null);
                    }}
                  />
                ))}
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
              !selectedCandidate
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
