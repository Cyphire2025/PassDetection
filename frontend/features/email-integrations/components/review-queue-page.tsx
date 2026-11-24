"use client";

import { useState } from "react";
import { Button, Card, CardContent } from "@/components/ui";
import { useEmailReviews, useResolveEmailReview } from "../hooks/use-email-integrations";
import type { EmailReviewAction, EmailReviewItem } from "../types";
import { EmailCardSkeletons, EmailDialog, EmailNotice, EmailQueryError } from "./email-integrations-ui";
import { EmailReviewCard, type ActionConfirmation } from "./email-review-card";
import { MatchReviewDialog } from "./match-review-dialog";

const REVIEW_STATUSES = [
  { value: "open", label: "Needs review", emptyTitle: "No items needing review" },
  { value: "deferred", label: "Deferred", emptyTitle: "No deferred items" },
  { value: "resolved", label: "Resolved", emptyTitle: "No resolved items" },
  { value: "rejected", label: "Rejected", emptyTitle: "No rejected items" },
  { value: "cancelled", label: "Cancelled", emptyTitle: "No cancelled items" },
  { value: "all", label: "All history", emptyTitle: "No email review history" },
] as const;

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
          {reviews.data.map((item) => (
            <EmailReviewCard key={item.id} item={item} resolve={resolve}
              isBusy={resolve.isPending && activeReviewId === item.id}
              onMatch={setMatchTarget} onConfirm={setConfirmation} onResolve={resolveItem} />
          ))}
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

