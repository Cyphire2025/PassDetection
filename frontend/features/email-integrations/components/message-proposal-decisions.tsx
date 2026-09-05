"use client";
import { Button } from "@/components/ui";
import { useState } from "react";
import { useDecideEmailProposal } from "../hooks/use-email-integrations";
import type { EmailInboxProposal, EmailProposalDecisionAction } from "../types";
import { formatEmailLabel } from "../utils/email-integrations";
import { EmailDialog, EmailNotice } from "./email-integrations-ui";
import { proposalActionLabel, readActionError } from "./message-activity-model";

export function ProposalDecisionButtons({
  proposal,
}: {
  proposal: EmailInboxProposal;
}) {
  const decide = useDecideEmailProposal();
  const [selection, setSelection] = useState<{
    action: EmailProposalDecisionAction;
    revision: number;
  } | null>(null);
  const [note, setNote] = useState("");
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  if (proposal.allowed_actions.length === 0 && !successMessage) return null;

  function closeDialog() {
    if (decide.isPending) return;
    setSelection(null);
    setNote("");
    decide.reset();
  }

  function submitDecision() {
    if (!selection) return;
    decide.mutate(
      {
        proposalId: proposal.id,
        request: {
          action: selection.action,
          expected_revision: selection.revision,
          ...(note.trim() ? { note: note.trim() } : {}),
        },
      },
      {
        onSuccess: (response) => {
          setSuccessMessage(response.message);
          setSelection(null);
          setNote("");
        },
      },
    );
  }

  return (
    <div className="mt-3 space-y-3">
      {successMessage && (
        <EmailNotice tone="success">{successMessage}</EmailNotice>
      )}
      {!successMessage && (
        <div className="flex flex-wrap gap-2">
          {proposal.allowed_actions.map((action) => (
            <Button
              key={action}
              type="button"
              size="sm"
              variant={
                action === "reject"
                  ? "danger"
                  : action === "approve"
                    ? "primary"
                    : "secondary"
              }
              onClick={() => {
                decide.reset();
                setSelection({
                  action,
                  revision: proposal.revision,
                });
              }}
            >
              {proposalActionLabel(action)}
            </Button>
          ))}
        </div>
      )}

      {selection && (
        <EmailDialog
          title={`${proposalActionLabel(selection.action)} this proposal?`}
          description="The decision is recorded against the current revision. It does not send email or execute a high-risk external change."
          isBusy={decide.isPending}
          onClose={closeDialog}
        >
          <div className="space-y-4">
            <div className="rounded-lg bg-slate-50 p-4">
              <p className="text-sm font-semibold text-slate-900">
                {formatEmailLabel(proposal.action_type)}
              </p>
              <p className="mt-1 text-sm text-slate-600">
                {proposal.explanation}
              </p>
            </div>
            <label className="block text-sm font-medium text-slate-700">
              Decision note (optional)
              <textarea
                value={note}
                maxLength={1000}
                rows={3}
                className="mt-1.5 w-full resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition-colors focus:border-transparent focus:ring-2 focus:ring-blue-600"
                onChange={(event) => setNote(event.target.value)}
              />
            </label>
            {decide.isError && (
              <EmailNotice tone="error">
                {readActionError(
                  decide.error,
                  "The proposal decision could not be saved.",
                )}
              </EmailNotice>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                variant="secondary"
                disabled={decide.isPending}
                onClick={closeDialog}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant={selection.action === "reject" ? "danger" : "primary"}
                isLoading={decide.isPending}
                onClick={submitDecision}
              >
                Confirm {proposalActionLabel(selection.action).toLowerCase()}
              </Button>
            </div>
          </div>
        </EmailDialog>
      )}
    </div>
  );
}
