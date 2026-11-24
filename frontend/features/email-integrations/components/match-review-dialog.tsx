"use client";

import { useState } from "react";
import { Button } from "@/components/ui";
import { useEmailReviewOptions, useResolveEmailReview } from "../hooks/use-email-integrations";
import type { EmailReviewItem } from "../types";
import { EmailDialog, EmailNotice } from "./email-integrations-ui";

export function MatchReviewDialog({
  item,
  onClose,
  onSaved,
}: {
  item: EmailReviewItem;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [groupId, setGroupId] = useState(item.proposed_group_id ?? "");
  const [passengerId, setPassengerId] = useState(
    item.proposed_passenger_id ?? "",
  );
  const [documentType, setDocumentType] = useState<
    "" | "visa" | "flight_ticket"
  >(
    item.artifact_detected_type === "visa"
      || item.artifact_detected_type === "flight_ticket"
      ? item.artifact_detected_type
      : "",
  );
  const groups = useEmailReviewOptions();
  const passengers = useEmailReviewOptions(groupId || undefined);
  const resolve = useResolveEmailReview();

  function saveMatch() {
    if (!groupId || !passengerId || !documentType) return;
    resolve.mutate(
      {
        reviewId: item.id,
        request: {
          action: "assign",
          group_id: groupId,
          passenger_id: passengerId,
          document_type: documentType,
          expected_revision: item.revision,
        },
      },
      { onSuccess: (response) => onSaved(response.message) },
    );
  }

  return (
    <EmailDialog
      title="Assign email document"
      description="Select the verified document type, group, and passenger for this email item."
      isBusy={resolve.isPending}
      onClose={onClose}
    >
      <div className="space-y-4">
        {(groups.isError || passengers.isError) && (
          <EmailNotice tone="error">
            Match options could not be loaded. Please close this dialog and try
            again.
          </EmailNotice>
        )}
        {resolve.isError && (
          <EmailNotice tone="error">
            The selected match could not be saved. The review item may have
            changed; refresh the queue and try again.
          </EmailNotice>
        )}
        <label className="block text-sm font-medium text-slate-700">
          Document type
          <select
            value={documentType}
            disabled={resolve.isPending}
            onChange={(event) =>
              setDocumentType(
                event.target.value as "" | "visa" | "flight_ticket",
              )
            }
            className="mt-1 block h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:bg-slate-100"
          >
            <option value="">Select a document type</option>
            <option value="visa">Visa</option>
            <option value="flight_ticket">Flight ticket</option>
          </select>
        </label>
        <label className="block text-sm font-medium text-slate-700">
          Group
          <select
            value={groupId}
            disabled={groups.isLoading || groups.isError || resolve.isPending}
            onChange={(event) => {
              setGroupId(event.target.value);
              setPassengerId("");
            }}
            className="mt-1 block h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:bg-slate-100"
          >
            <option value="">Select a group</option>
            {groups.data?.groups.map((group) => (
              <option key={group.id} value={group.id}>
                {group.name}
                {group.destination ? ` — ${group.destination}` : ""}
                {group.travel_date ? ` — ${group.travel_date}` : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm font-medium text-slate-700">
          Passenger
          <select
            value={passengerId}
            disabled={
              !groupId
              || passengers.isLoading
              || passengers.isError
              || resolve.isPending
            }
            onChange={(event) => setPassengerId(event.target.value)}
            className="mt-1 block h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:bg-slate-100"
          >
            <option value="">Select a passenger</option>
            {passengers.data?.passengers.map((passenger) => (
              <option key={passenger.id} value={passenger.id}>
                {passenger.name}
                {passenger.passport_number_hint
                  ? ` — ${passenger.passport_number_hint}`
                  : ""}
              </option>
            ))}
          </select>
        </label>
        <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
          <Button
            type="button"
            variant="secondary"
            disabled={resolve.isPending}
            onClick={onClose}
          >
            Cancel
          </Button>
          <Button
            type="button"
            disabled={
              !groupId
              || !passengerId
              || !documentType
              || groups.isError
              || passengers.isError
            }
            isLoading={resolve.isPending}
            onClick={saveMatch}
          >
            Save match
          </Button>
        </div>
      </div>
    </EmailDialog>
  );
}

