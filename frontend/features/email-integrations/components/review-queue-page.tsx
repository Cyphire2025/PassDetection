"use client";

import Link from "next/link";
import { Check, Clock3, RefreshCw, Search, X } from "lucide-react";
import { useState } from "react";
import { Button, Card, CardContent } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import {
  formatConfidence,
  formatDateTime,
} from "@/lib/utils/format";
import {
  useEmailReviewOptions,
  useEmailReviews,
  useResolveEmailReview,
} from "../hooks/use-email-integrations";
import type {
  EmailReviewAction,
  EmailReviewItem,
} from "../types";
import { formatEmailLabel } from "../utils/email-integrations";
import {
  Definition,
  EmailCardSkeletons,
  EmailDialog,
  EmailNotice,
  EmailQueryError,
  EmailStatusBadge,
} from "./email-integrations-ui";

const REVIEW_STATUSES = [
  { value: "open", label: "Needs review", emptyTitle: "No items needing review" },
  { value: "deferred", label: "Deferred", emptyTitle: "No deferred items" },
  { value: "resolved", label: "Resolved", emptyTitle: "No resolved items" },
  { value: "rejected", label: "Rejected", emptyTitle: "No rejected items" },
  { value: "cancelled", label: "Cancelled", emptyTitle: "No cancelled items" },
  { value: "all", label: "All history", emptyTitle: "No email review history" },
] as const;

type ActionConfirmation = {
  item: EmailReviewItem;
  action: "mark_unrelated" | "reject";
};

export function EmailReviewQueuePage() {
  const [status, setStatus] = useState("open");
  const [notice, setNotice] = useState<string | null>(null);
  const [matchTarget, setMatchTarget] = useState<EmailReviewItem | null>(null);
  const [confirmation, setConfirmation] =
    useState<ActionConfirmation | null>(null);
  const [activeReviewId, setActiveReviewId] = useState<string | null>(null);
  const reviews = useEmailReviews(status);
  const resolve = useResolveEmailReview();

  function resolveItem(item: EmailReviewItem, action: EmailReviewAction) {
    setNotice(null);
    setActiveReviewId(item.id);
    resolve.mutate(
      {
        reviewId: item.id,
        request: {
          action,
          expected_revision: item.revision,
        },
      },
      {
        onSuccess: (response) => {
          setActiveReviewId(null);
          setConfirmation(null);
          setNotice(response.message);
        },
        onError: () => {
          setActiveReviewId(null);
        },
      },
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.035em] text-slate-950 sm:text-[30px]">
            Email review queue
          </h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">
            Resolve only uncertain, conflicting, or sensitive email processing
            decisions.
          </p>
        </div>
        <label className="text-sm font-medium text-slate-700">
          Review status
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="mt-1 block h-9 min-w-48 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
          >
            {REVIEW_STATUSES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {notice && <EmailNotice tone="success">{notice}</EmailNotice>}
      {resolve.isError && (
        <EmailNotice tone="error">
          The review decision could not be saved. The item may have changed;
          refresh the queue and try again.
        </EmailNotice>
      )}

      {reviews.isLoading ? (
        <EmailCardSkeletons />
      ) : reviews.isError ? (
        <EmailQueryError
          title="The email review queue could not be loaded."
          onRetry={() => void reviews.refetch()}
        />
      ) : reviews.data?.length ? (
        <div className="space-y-4">
          {reviews.data.map((item) => {
            const canResolve =
              item.status === "open" || item.status === "deferred";
            const allowedActions = new Set(item.allowed_actions);
            const isBusy = resolve.isPending && activeReviewId === item.id;
            return (
              <Card key={item.id}>
                <CardContent className="space-y-5 p-5">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <EmailStatusBadge status={item.status} />
                        <span className="text-xs font-medium text-slate-500">
                          {formatEmailLabel(item.review_type)}
                        </span>
                      </div>
                      <h2 className="mt-2 break-words text-base font-semibold text-slate-950">
                        {item.subject || "No subject"}
                      </h2>
                      <p className="mt-1 break-all text-sm text-slate-600">
                        From {item.sender_email}
                      </p>
                    </div>
                    <Link
                      href={ROUTES.dashboard.emailIntegrationMessage(
                        item.email_message_id,
                      ) as never}
                      className="shrink-0 text-sm font-medium text-blue-700 hover:text-blue-800 hover:underline"
                    >
                      View source email
                    </Link>
                  </div>

                  <dl className="grid gap-4 rounded-lg bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-4">
                    <Definition term="Received">
                      {formatDateTime(item.received_at)}
                    </Definition>
                    <Definition term="Attachment or link">
                      {item.artifact_name ?? formatEmailLabel(item.artifact_kind)}
                    </Definition>
                    <Definition term="Proposed match">
                      {item.proposed_passenger_name
                        ? `${item.proposed_passenger_name}${item.proposed_group_name ? ` — ${item.proposed_group_name}` : ""}`
                        : item.proposed_group_name ?? "No confident match"}
                    </Definition>
                    <Definition term="Confidence">
                      {formatConfidence(item.confidence)}
                    </Definition>
                  </dl>

                  <div className="grid gap-4 lg:grid-cols-3">
                    <EvidenceList
                      title="Matching evidence"
                      items={item.evidence}
                      emptyText="No supporting evidence was recorded."
                    />
                    <EvidenceList
                      title="Detected conflicts"
                      items={item.conflicts}
                      emptyText="No conflicts were detected."
                      tone={item.conflicts.length > 0 ? "warning" : "neutral"}
                    />
                    <div className="rounded-lg border border-slate-200 p-4">
                      <h3 className="text-sm font-semibold text-slate-900">
                        Proposed action
                      </h3>
                      <p className="mt-2 text-sm text-slate-700">
                        {formatEmailLabel(item.proposed_action)}
                      </p>
                    </div>
                  </div>

                  {canResolve && (
                    <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4">
                      {allowedActions.has("approve") && (
                        <Button
                          type="button"
                          size="sm"
                          leftIcon={<Check className="h-3.5 w-3.5" aria-hidden="true" />}
                          isLoading={isBusy && resolve.variables?.request.action === "approve"}
                          disabled={resolve.isPending}
                          onClick={() => resolveItem(item, "approve")}
                        >
                          Approve suggestion
                        </Button>
                      )}
                      {allowedActions.has("assign") && (
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          leftIcon={<Search className="h-3.5 w-3.5" aria-hidden="true" />}
                          disabled={resolve.isPending}
                          onClick={() => setMatchTarget(item)}
                        >
                          Choose another match
                        </Button>
                      )}
                      {allowedActions.has("retry") && (
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          leftIcon={<RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />}
                          isLoading={isBusy && resolve.variables?.request.action === "retry"}
                          disabled={resolve.isPending}
                          onClick={() => resolveItem(item, "retry")}
                        >
                          Retry processing
                        </Button>
                      )}
                      {allowedActions.has("defer") && (
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          leftIcon={<Clock3 className="h-3.5 w-3.5" aria-hidden="true" />}
                          isLoading={isBusy && resolve.variables?.request.action === "defer"}
                          disabled={resolve.isPending}
                          onClick={() => resolveItem(item, "defer")}
                        >
                          Defer
                        </Button>
                      )}
                      {allowedActions.has("mark_unrelated") && (
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          disabled={resolve.isPending}
                          onClick={() =>
                            setConfirmation({ item, action: "mark_unrelated" })
                          }
                        >
                          Mark unrelated
                        </Button>
                      )}
                      {allowedActions.has("reject") && (
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="text-red-700 hover:bg-red-50 hover:text-red-800"
                          leftIcon={<X className="h-3.5 w-3.5" aria-hidden="true" />}
                          disabled={resolve.isPending}
                          onClick={() =>
                            setConfirmation({ item, action: "reject" })
                          }
                        >
                          Reject
                        </Button>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      ) : (
        <Card className="border-dashed">
          <CardContent className="px-6 py-12 text-center">
            <h2 className="font-semibold text-slate-900">
              {REVIEW_STATUSES.find((option) => option.value === status)
                ?.emptyTitle ?? "No review items"}
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              Successfully processed emails remain in Activity and do not
              clutter this queue.
            </p>
          </CardContent>
        </Card>
      )}

      {matchTarget && (
        <MatchReviewDialog
          key={matchTarget.id}
          item={matchTarget}
          onClose={() => setMatchTarget(null)}
          onSaved={(message) => {
            setMatchTarget(null);
            setNotice(message);
          }}
        />
      )}

      {confirmation && (
        <EmailDialog
          title={
            confirmation.action === "mark_unrelated"
              ? "Mark this entire email as unrelated?"
              : "Reject this suggested result?"
          }
          description={
            confirmation.action === "mark_unrelated"
              ? "This marks the entire source email as unrelated and cancels all other open or deferred review items from the same email. None of those items will enter a travel document workflow."
              : "The proposed processing result will be rejected and retained in activity history."
          }
          isBusy={resolve.isPending}
          onClose={() => setConfirmation(null)}
        >
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="secondary"
              disabled={resolve.isPending}
              onClick={() => setConfirmation(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant={
                confirmation.action === "reject" ? "danger" : "primary"
              }
              isLoading={resolve.isPending}
              onClick={() =>
                resolveItem(confirmation.item, confirmation.action)
              }
            >
              {confirmation.action === "reject"
                ? "Reject result"
                : "Mark unrelated"}
            </Button>
          </div>
        </EmailDialog>
      )}
    </div>
  );
}

function MatchReviewDialog({
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

function EvidenceList({
  title,
  items,
  emptyText,
  tone = "neutral",
}: {
  title: string;
  items: string[];
  emptyText: string;
  tone?: "neutral" | "warning";
}) {
  return (
    <div
      className={`rounded-lg border p-4 ${
        tone === "warning"
          ? "border-amber-200 bg-amber-50/60"
          : "border-slate-200"
      }`}
    >
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      {items.length > 0 ? (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
          {items.map((item, index) => (
            <li key={`${item}-${index}`}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-slate-600">{emptyText}</p>
      )}
    </div>
  );
}
