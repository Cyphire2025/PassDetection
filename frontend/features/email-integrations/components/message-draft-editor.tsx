"use client";
import { Button, Input } from "@/components/ui";
import { useState } from "react";
import {
  useDecideEmailReplyDraft,
  useUpdateEmailReplyDraft,
} from "../hooks/use-email-integrations";
import type { EmailDraftDecisionAction, EmailInboxDraft } from "../types";
import { EmailDialog, EmailNotice } from "./email-integrations-ui";
import { readActionError } from "./message-activity-model";

export function DraftEditor({ draft }: { draft: EmailInboxDraft }) {
  const updateDraft = useUpdateEmailReplyDraft();
  const decideDraft = useDecideEmailReplyDraft();
  const [isOpen, setIsOpen] = useState(false);
  const [subject, setSubject] = useState(draft.subject);
  const [body, setBody] = useState(draft.body_text);
  const [editorRevision, setEditorRevision] = useState<number | null>(null);
  const [decision, setDecision] = useState<{
    action: EmailDraftDecisionAction;
    revision: number;
  } | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const canEdit = ["prepared", "edited"].includes(draft.status);
  const canApprove = ["prepared", "edited"].includes(draft.status);
  const canDismiss = ["prepared", "edited", "approved"].includes(draft.status);
  const isValid = subject.trim().length > 0 && body.trim().length > 0;

  function openEditor() {
    setSubject(draft.subject);
    setBody(draft.body_text);
    setEditorRevision(draft.revision);
    setSuccessMessage(null);
    updateDraft.reset();
    setIsOpen(true);
  }

  function closeEditor() {
    if (updateDraft.isPending) return;
    setIsOpen(false);
    setEditorRevision(null);
    updateDraft.reset();
  }

  function saveDraft() {
    if (!isValid || editorRevision === null) return;
    updateDraft.mutate(
      {
        draftId: draft.id,
        request: {
          subject: subject.trim(),
          body_text: body.trim(),
          expected_revision: editorRevision,
        },
      },
      {
        onSuccess: () => {
          setIsOpen(false);
          setEditorRevision(null);
          setSuccessMessage("Draft changes saved. Sending remains manual.");
        },
      },
    );
  }

  function openDecision(action: EmailDraftDecisionAction) {
    decideDraft.reset();
    setSuccessMessage(null);
    setDecision({ action, revision: draft.revision });
  }

  function closeDecision() {
    if (decideDraft.isPending) return;
    setDecision(null);
    decideDraft.reset();
  }

  function submitDecision() {
    if (!decision) return;
    decideDraft.mutate(
      {
        draftId: draft.id,
        request: {
          action: decision.action,
          expected_revision: decision.revision,
        },
      },
      {
        onSuccess: (updated) => {
          setDecision(null);
          setSuccessMessage(
            updated.status === "approved"
              ? "Draft approved for manual use. No email was sent."
              : "Prepared draft dismissed. No email was sent.",
          );
        },
      },
    );
  }

  return (
    <div className="space-y-3">
      {successMessage && (
        <EmailNotice tone="success">{successMessage}</EmailNotice>
      )}
      <div className="flex flex-wrap gap-2">
        {canEdit && (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={openEditor}
          >
            Correct bad draft
          </Button>
        )}
        {canApprove && (
          <Button
            type="button"
            size="sm"
            onClick={() => openDecision("approve")}
          >
            Approve draft
          </Button>
        )}
        {canDismiss && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => openDecision("dismiss")}
          >
            Dismiss draft
          </Button>
        )}
      </div>
      {!canEdit && !canDismiss && (
        <p className="text-xs text-slate-500">
          This draft is closed and can no longer be edited.
        </p>
      )}

      {isOpen && (
        <EmailDialog
          title="Correct the prepared reply"
          description="Saving applies the corrected draft and records feedback in the audit trail. No message will be sent."
          isBusy={updateDraft.isPending}
          onClose={closeEditor}
        >
          <div className="space-y-4">
            <p className="text-xs text-slate-500">
              Recipients:{" "}
              {draft.recipients.length
                ? draft.recipients.join(", ")
                : "Not provided"}
            </p>
            <Input
              label="Subject"
              required
              value={subject}
              maxLength={998}
              onChange={(event) => setSubject(event.target.value)}
            />
            <label className="block text-sm font-medium text-slate-700">
              Draft message
              <textarea
                required
                value={body}
                maxLength={20_000}
                rows={10}
                className="mt-1.5 w-full resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none transition-colors focus:border-transparent focus:ring-2 focus:ring-blue-600"
                onChange={(event) => setBody(event.target.value)}
              />
            </label>
            <EmailNotice tone="info">
              Prepared draft — sending remains manual.
            </EmailNotice>
            {updateDraft.isError && (
              <EmailNotice tone="error">
                {readActionError(
                  updateDraft.error,
                  "The prepared draft could not be updated.",
                )}
              </EmailNotice>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                variant="secondary"
                disabled={updateDraft.isPending}
                onClick={closeEditor}
              >
                Cancel
              </Button>
              <Button
                type="button"
                isLoading={updateDraft.isPending}
                disabled={!isValid}
                onClick={saveDraft}
              >
                Save draft
              </Button>
            </div>
          </div>
        </EmailDialog>
      )}
      {decision && (
        <EmailDialog
          title={
            decision.action === "approve"
              ? "Approve this prepared draft?"
              : "Dismiss this prepared draft?"
          }
          description={
            decision.action === "approve"
              ? "Approval records that the draft is ready for manual use. The platform will not send it."
              : "Dismissal removes the draft from active work. The source email remains unchanged."
          }
          isBusy={decideDraft.isPending}
          onClose={closeDecision}
        >
          <div className="space-y-4">
            <div className="rounded-lg bg-slate-50 p-4 text-sm text-slate-700">
              <p className="font-semibold text-slate-900">{draft.subject}</p>
              <p className="mt-2 line-clamp-4 whitespace-pre-wrap">
                {draft.body_text}
              </p>
            </div>
            {decideDraft.isError && (
              <EmailNotice tone="error">
                {readActionError(
                  decideDraft.error,
                  "The draft decision could not be saved.",
                )}
              </EmailNotice>
            )}
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="secondary"
                disabled={decideDraft.isPending}
                onClick={closeDecision}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant={decision.action === "dismiss" ? "danger" : "primary"}
                isLoading={decideDraft.isPending}
                onClick={submitDecision}
              >
                Confirm {decision.action}
              </Button>
            </div>
          </div>
        </EmailDialog>
      )}
    </div>
  );
}
