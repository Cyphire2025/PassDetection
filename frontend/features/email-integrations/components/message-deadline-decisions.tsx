"use client";
import { Button } from "@/components/ui";
import { useState } from "react";
import { useDecideEmailDeadline } from "../hooks/use-email-integrations";
import type {
  EmailActiveDeadlineStatus,
  EmailDeadlineDecisionAction,
  EmailInboxDeadline,
} from "../types";
import { EmailDialog, EmailNotice } from "./email-integrations-ui";
import {
  deadlineActionLabel,
  isActiveDeadlineStatus,
  readActionError,
} from "./message-activity-model";

export function DeadlineDecisionButtons({
  deadline,
}: {
  deadline: EmailInboxDeadline;
}) {
  const decide = useDecideEmailDeadline();
  const [selection, setSelection] = useState<{
    action: EmailDeadlineDecisionAction;
    status: EmailActiveDeadlineStatus;
    updatedAt: string;
  } | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const activeStatus = isActiveDeadlineStatus(deadline.status)
    ? deadline.status
    : null;
  const actions: EmailDeadlineDecisionAction[] =
    activeStatus === null
      ? []
      : activeStatus === "acknowledged"
        ? ["complete", "dismiss"]
        : ["acknowledge", "complete", "dismiss"];

  function closeDialog() {
    if (decide.isPending) return;
    setSelection(null);
    decide.reset();
  }

  function submitDecision() {
    if (!selection) return;
    decide.mutate(
      {
        deadlineId: deadline.id,
        request: {
          action: selection.action,
          expected_status: selection.status,
          expected_updated_at: selection.updatedAt,
        },
      },
      {
        onSuccess: (updated) => {
          setSelection(null);
          setSuccessMessage(
            updated.status === "acknowledged"
              ? "Deadline acknowledged."
              : updated.status === "completed"
                ? "Deadline marked complete."
                : "Deadline dismissed.",
          );
        },
      },
    );
  }

  if (actions.length === 0 && !successMessage) return null;

  return (
    <div className="mt-3 space-y-2">
      {successMessage && (
        <EmailNotice tone="success">{successMessage}</EmailNotice>
      )}
      {activeStatus && (
        <div className="flex flex-wrap gap-2">
          {actions.map((action) => (
            <Button
              key={action}
              type="button"
              size="sm"
              variant={action === "dismiss" ? "ghost" : "secondary"}
              onClick={() => {
                decide.reset();
                setSelection({
                  action,
                  status: activeStatus,
                  updatedAt: deadline.updated_at,
                });
              }}
            >
              {deadlineActionLabel(action)}
            </Button>
          ))}
        </div>
      )}
      {selection && (
        <EmailDialog
          title={`${deadlineActionLabel(selection.action)} this deadline?`}
          description="This updates the stored operational deadline only. It does not send a message or change the source email."
          isBusy={decide.isPending}
          onClose={closeDialog}
        >
          <div className="space-y-4">
            <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-700">
              {deadline.source_phrase}
            </p>
            {decide.isError && (
              <EmailNotice tone="error">
                {readActionError(
                  decide.error,
                  "The deadline decision could not be saved.",
                )}
              </EmailNotice>
            )}
            <div className="flex justify-end gap-2">
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
                isLoading={decide.isPending}
                onClick={submitDecision}
              >
                Confirm
              </Button>
            </div>
          </div>
        </EmailDialog>
      )}
    </div>
  );
}
