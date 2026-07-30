"use client";

import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  ExternalLink,
  FileEdit,
  FileText,
  RefreshCw,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
} from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import {
  formatBytes,
  formatConfidence,
  formatDateTime,
} from "@/lib/utils/format";
import { useState } from "react";
import {
  useCreateEmailIntelligenceFeedback,
  useDecideEmailDeadline,
  useDecideEmailProposal,
  useDecideEmailReplyDraft,
  useEmailMessage,
  useEmailMessageIntelligence,
  useEmailReviewOptions,
  useRetryEmailIntelligence,
  useUpdateEmailReplyDraft,
} from "../hooks/use-email-integrations";
import type {
  EmailActiveDeadlineStatus,
  EmailAiCorrectionField,
  EmailAiCorrectionValue,
  EmailDeadlineDecisionAction,
  EmailDraftDecisionAction,
  EmailInboxDeadline,
  EmailInboxDraft,
  EmailInboxProposal,
  EmailIntelligenceDetail,
  EmailProposalDecisionAction,
} from "../types";
import {
  formatEmailLabel,
} from "../utils/email-integrations";
import {
  Definition,
  EmailCardSkeletons,
  EmailDialog,
  EmailNotice,
  EmailQueryError,
  EmailStatusBadge,
} from "./email-integrations-ui";

export function EmailMessageActivityPage({
  messageId,
}: {
  messageId: string;
}) {
  const message = useEmailMessage(messageId);
  const intelligence = useEmailMessageIntelligence(messageId, {
    pollWhileMissing: Boolean(message.data),
  });

  if (message.isLoading) return <EmailCardSkeletons count={2} />;
  if (message.isError || !message.data) {
    return (
      <div className="space-y-4">
        <Link
          href={ROUTES.dashboard.emailIntegrationsActivity as never}
          className="inline-flex items-center gap-1 text-sm font-medium text-blue-700 hover:underline"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Back to activity
        </Link>
        <EmailQueryError
          title="This email activity record could not be loaded."
          onRetry={() => void message.refetch()}
        />
      </div>
    );
  }

  const data = message.data;
  const intelligenceDetail = intelligence.data ?? null;
  const intelligenceSummary = intelligenceDetail?.summary;
  const intelligenceCategory = intelligenceDetail?.status;
  const intelligencePriority = intelligenceDetail?.priority;
  const detectedIntent = intelligenceDetail?.intent;
  const requestedActions = intelligenceDetail?.missing_information ?? [];
  const deadlines = intelligenceDetail?.deadlines ?? [];
  const risks = intelligenceDetail?.risks ?? [];
  const actionProposals = intelligenceDetail?.proposals ?? [];
  const replyDraft = intelligenceDetail?.draft;
  const hasApprovalRequired = actionProposals.some(
    (proposal) =>
      proposal.requires_approval
      && proposal.allowed_actions.includes("approve"),
  );

  return (
    <div className="space-y-6">
      <div>
        <Link
          href={ROUTES.dashboard.emailIntegrationsActivity as never}
          className="inline-flex items-center gap-1 text-sm font-medium text-blue-700 hover:underline"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Back to activity
        </Link>
        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h1 className="break-words text-2xl font-bold tracking-tight text-slate-950">
              {data.subject || "No subject"}
            </h1>
            <p className="mt-1 break-all text-sm text-slate-600">
              From {data.sender_name ? `${data.sender_name} — ` : ""}
              {data.sender_email}
            </p>
          </div>
          <EmailStatusBadge status={data.processing_status} />
        </div>
      </div>

      <Card>
        <CardHeader className="p-5 pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle>Source email</CardTitle>
            {data.original_email_url && (
              <a
                href={data.original_email_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-sm font-semibold text-blue-700 hover:underline"
              >
                Open original email
                <ExternalLink className="h-4 w-4" aria-hidden="true" />
              </a>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-5 p-5 pt-0">
          <dl className="grid gap-4 rounded-lg bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-4">
            <Definition term="Connected inbox">
              {data.account_email}
            </Definition>
            <Definition term="Received">
              {formatDateTime(data.received_at)}
            </Definition>
            <Definition term="Recipients">
              {data.recipients.length > 0
                ? data.recipients.join(", ")
                : "Not available"}
            </Definition>
            <Definition term="Matched group">
              {data.group_name ?? "Not matched"}
            </Definition>
          </dl>
          <div>
            <h2 className="text-sm font-semibold text-slate-900">
              Message excerpt
            </h2>
            <p className="mt-2 whitespace-pre-wrap break-words rounded-lg border border-slate-200 bg-white p-4 text-sm leading-6 text-slate-700">
              {data.body_excerpt || "No message excerpt was retained."}
            </p>
          </div>
        </CardContent>
      </Card>

      {intelligence.isLoading && <EmailCardSkeletons count={1} />}
      {intelligence.isError && (
        <EmailQueryError
          title="The optional AI operational brief could not be loaded."
          onRetry={() => void intelligence.refetch()}
        />
      )}
      {!intelligence.isLoading
        && !intelligence.isError
        && intelligence.data === null && (
        <Card className="border-dashed">
          <CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-slate-900">
                AI operational brief is not available yet
              </p>
              <p className="mt-1 text-sm text-slate-600">
                Analysis may still be queued, or AI may not be enabled for this
                connected inbox.
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => void intelligence.refetch()}
            >
              Refresh brief
            </Button>
          </CardContent>
        </Card>
      )}
      {intelligenceDetail && (
        <section
          aria-labelledby="operational-intelligence-heading"
          className="space-y-4"
        >
          <div className="flex items-center gap-2">
            <span className="rounded-lg bg-blue-50 p-2 text-blue-700">
              <Sparkles className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <h2
                id="operational-intelligence-heading"
                className="text-base font-semibold text-slate-900"
              >
                AI operational brief
              </h2>
              <p className="text-sm text-slate-500">
                Extracted guidance is evidence for review, not an instruction
                to send or change email.
              </p>
            </div>
          </div>

          {intelligenceDetail.needs_attention && (
            <EmailNotice tone="warning">
              Human review is required before relying on this analysis
              {intelligenceDetail.missing_information.length
                ? `: ${intelligenceDetail.missing_information.join("; ")}`
                : "."}
            </EmailNotice>
          )}

          <Card>
            <CardContent className="space-y-5 p-5">
              <dl className="grid gap-4 rounded-lg bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-3">
                <Definition term="Analysis status">
                  {formatEmailLabel(intelligenceCategory)}
                </Definition>
                <Definition term="Priority">
                  <EmailStatusBadge status={intelligencePriority} />
                </Definition>
                <Definition term="Detected intent">
                  {formatEmailLabel(detectedIntent)}
                </Definition>
                <Definition term="AI confidence">
                  {formatConfidence(intelligenceDetail.confidence)}
                </Definition>
                <Definition term="AI linked group">
                  {intelligenceDetail.linked_group_name
                    ?? "No visible group match"}
                </Definition>
                <Definition term="AI linked passengers">
                  {intelligenceDetail.linked_passengers.length
                    ? intelligenceDetail.linked_passengers
                        .map((passenger) => passenger.name)
                        .join(", ")
                    : "No visible passenger match"}
                </Definition>
              </dl>

              {intelligenceDetail.candidate_links.length > 0 && (
                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold text-slate-900">
                      Visible match candidates
                    </h3>
                    {!intelligenceDetail.candidate_links.some(
                      (candidate) => candidate.canonical,
                    ) && (
                      <Badge variant="warning">Selection needs review</Badge>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    These candidates were rechecked against records you can
                    currently view. Confidence and reasoning are AI evidence,
                    not proof.
                  </p>
                  <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                    {intelligenceDetail.candidate_links.map((candidate) => (
                      <li
                        key={`${candidate.entity_type}-${candidate.entity_id}`}
                        className="rounded-lg border border-slate-200 p-3"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-medium text-slate-900">
                            {candidate.name}
                          </p>
                          <Badge variant="outline">
                            {formatEmailLabel(candidate.entity_type)}
                          </Badge>
                          {candidate.canonical && (
                            <Badge variant="success">Linked</Badge>
                          )}
                        </div>
                        <p className="mt-1 text-xs text-slate-500">
                          {formatConfidence(candidate.confidence)} confidence
                        </p>
                        <p className="mt-2 text-xs leading-5 text-slate-600">
                          {candidate.rationale}
                        </p>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {intelligenceSummary && (
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">
                    Operational summary
                  </h3>
                  <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">
                    {intelligenceSummary}
                  </p>
                </div>
              )}

              {requestedActions.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">
                    Missing information
                  </h3>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
                    {requestedActions.map((action, index) => (
                      <li key={`${action}-${index}`}>{action}</li>
                    ))}
                  </ul>
                </div>
              )}

              {intelligenceDetail.evidence.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">
                    Analysis evidence
                  </h3>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
                    {intelligenceDetail.evidence.map((evidence, index) => (
                      <li key={`${evidence}-${index}`}>{evidence}</li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>

          {(deadlines.length > 0 || risks.length > 0) && (
            <div className="grid gap-4 lg:grid-cols-2">
              {deadlines.length > 0 && (
                <Card>
                  <CardHeader className="p-5 pb-3">
                    <CardTitle className="flex items-center gap-2">
                      <CalendarClock
                        className="h-5 w-5 text-amber-600"
                        aria-hidden="true"
                      />
                      Detected deadlines
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-5 pt-0">
                    <ul className="space-y-3">
                      {deadlines.map((deadline, index) => (
                        <li
                          key={deadline.id ?? `${deadline.source_phrase}-${index}`}
                          className="rounded-lg border border-amber-200 bg-amber-50/60 p-3"
                        >
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <p className="text-sm font-medium text-amber-950">
                              {deadline.source_phrase}
                            </p>
                            <EmailStatusBadge status={deadline.status} />
                          </div>
                          <p className="mt-1 text-xs text-amber-800">
                            {deadline.due_at
                              ? formatDateTime(deadline.due_at)
                              : "A due time was mentioned but not confidently resolved."}
                            {deadline.source_timezone
                              ? ` · ${deadline.source_timezone}`
                              : ""}
                          </p>
                          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-amber-800">
                            <span>
                              {formatConfidence(deadline.confidence)} confidence
                            </span>
                            {deadline.is_ambiguous && (
                              <Badge variant="warning">Needs date review</Badge>
                            )}
                          </div>
                          <DeadlineDecisionButtons deadline={deadline} />
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}

              {risks.length > 0 && (
                <Card>
                  <CardHeader className="p-5 pb-3">
                    <CardTitle className="flex items-center gap-2">
                      <ShieldAlert
                        className="h-5 w-5 text-red-600"
                        aria-hidden="true"
                      />
                      Operational risks
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-5 pt-0">
                    <ul className="space-y-3">
                      {risks.map((risk, index) => (
                        <li
                          key={`${risk}-${index}`}
                          className="rounded-lg border border-red-200 bg-red-50/60 p-3"
                        >
                          <div className="flex items-start gap-2">
                            <AlertTriangle
                              className="mt-0.5 h-4 w-4 shrink-0 text-red-600"
                              aria-hidden="true"
                            />
                            <p className="text-sm text-red-900">
                              {risk}
                            </p>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}
            </div>
          )}

          {actionProposals.length > 0 && (
            <Card>
              <CardHeader className="p-5 pb-3">
                <CardTitle>Prepared actions</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 p-5 pt-0">
                <ul className="space-y-3">
                  {actionProposals.map((proposal, index) => (
                    <li
                      key={proposal.id || `${proposal.action_type}-${index}`}
                      className="rounded-lg border border-slate-200 p-4"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-semibold text-slate-900">
                          {formatEmailLabel(proposal.action_type)}
                        </p>
                        <Badge
                          variant={
                            proposal.requires_approval
                            && proposal.allowed_actions.includes("approve")
                              ? "warning"
                              : "outline"
                          }
                        >
                          {proposal.requires_approval
                          && proposal.allowed_actions.includes("approve")
                            ? "Approval required"
                            : "Policy reviewed"}
                        </Badge>
                        <Badge
                          variant={
                            ["high", "critical", "blocked"].includes(
                              proposal.risk_level.toLowerCase(),
                            )
                              ? "destructive"
                              : proposal.risk_level.toLowerCase() === "medium"
                                ? "warning"
                                : "outline"
                          }
                        >
                          {formatEmailLabel(proposal.risk_level)} risk
                        </Badge>
                        <EmailStatusBadge status={proposal.status} />
                      </div>
                      <p className="mt-2 text-sm text-slate-600">
                        {proposal.explanation}
                      </p>
                      <p className="mt-2 text-xs text-slate-500">
                        Confidence: {formatConfidence(proposal.confidence)}
                      </p>
                      <ProposalDecisionButtons proposal={proposal} />
                    </li>
                  ))}
                </ul>
                {hasApprovalRequired && (
                  <EmailNotice tone="info">
                    Approval records this decision only. It never sends email,
                    and high-risk actions remain blocked.
                  </EmailNotice>
                )}
              </CardContent>
            </Card>
          )}

          {replyDraft && (
            <Card className="border-blue-200">
              <CardHeader className="p-5 pb-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle className="flex items-center gap-2">
                    <FileEdit
                      className="h-5 w-5 text-blue-700"
                      aria-hidden="true"
                    />
                    Prepared reply draft
                  </CardTitle>
                  {["prepared", "edited"].includes(replyDraft.status) ? (
                    <Badge variant="outline">Manual review required</Badge>
                  ) : (
                    <EmailStatusBadge status={replyDraft.status} />
                  )}
                </div>
              </CardHeader>
              <CardContent className="space-y-3 p-5 pt-0">
                <dl className="grid gap-4 rounded-lg bg-slate-50 p-4 sm:grid-cols-2">
                  <Definition term="Recipients">
                    {replyDraft.recipients.length
                      ? replyDraft.recipients.join(", ")
                      : "Not provided"}
                  </Definition>
                  <Definition term="Subject">
                    {replyDraft.subject}
                  </Definition>
                </dl>
                <p className="whitespace-pre-wrap break-words rounded-lg border border-blue-100 bg-blue-50/60 p-4 text-sm leading-6 text-blue-950">
                  {replyDraft.body_text}
                </p>
                <p className="text-xs text-blue-800">
                  Prepared draft — sending remains manual. The platform cannot
                  send or delete messages in connected accounts.
                </p>
                <DraftEditor draft={replyDraft} />
              </CardContent>
            </Card>
          )}

          <IntelligenceFeedback
            messageId={messageId}
            intelligence={intelligenceDetail}
          />
        </section>
      )}

      <Card>
        <CardHeader className="p-5 pb-3">
          <CardTitle>Relevance decision</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 p-5 pt-0">
          <dl className="grid gap-4 sm:grid-cols-3">
            <Definition term="Decision">
              <EmailStatusBadge status={data.relevance_status} />
            </Definition>
            <Definition term="Confidence">
              {formatConfidence(data.relevance_confidence)}
            </Definition>
            <Definition term="AI used">
              {data.ai_used ? "Yes" : "No"}
            </Definition>
          </dl>
          <div>
            <h2 className="text-sm font-semibold text-slate-900">
              Recorded evidence
            </h2>
            {data.relevance_evidence.length > 0 ? (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
                {data.relevance_evidence.map((evidence, index) => (
                  <li key={`${evidence}-${index}`}>{evidence}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-slate-600">
                No relevance evidence was recorded.
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      <section aria-labelledby="email-artifacts-heading" className="space-y-3">
        <h2
          id="email-artifacts-heading"
          className="text-base font-semibold text-slate-900"
        >
          Retrieved items
        </h2>
        {data.artifacts.length > 0 ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {data.artifacts.map((artifact) => (
              <Card key={artifact.id}>
                <CardContent className="space-y-4 p-5">
                  <div className="flex items-start gap-3">
                    <span className="rounded-lg bg-slate-100 p-2 text-slate-600">
                      <FileText className="h-5 w-5" aria-hidden="true" />
                    </span>
                    <div className="min-w-0">
                      <h3 className="break-words font-semibold text-slate-900">
                        {artifact.filename ?? formatEmailLabel(artifact.kind)}
                      </h3>
                      <p className="mt-1 text-sm text-slate-600">
                        {formatEmailLabel(artifact.kind)}
                      </p>
                    </div>
                  </div>
                  <dl className="grid gap-4 sm:grid-cols-2">
                    <Definition term="Retrieval">
                      <EmailStatusBadge status={artifact.retrieval_status} />
                    </Definition>
                    <Definition term="Processing">
                      <EmailStatusBadge status={artifact.processing_status} />
                    </Definition>
                    <Definition term="Detected type">
                      {formatEmailLabel(artifact.detected_type)}
                    </Definition>
                    <Definition term="Match confidence">
                      {formatConfidence(artifact.match_confidence)}
                    </Definition>
                    <Definition term="File size">
                      {artifact.byte_size === null
                        ? "Not available"
                        : formatBytes(artifact.byte_size)}
                    </Definition>
                    <Definition term="Source">
                      {artifact.source_host ?? "Email attachment"}
                    </Definition>
                  </dl>
                  {artifact.error_message && (
                    <p
                      role="alert"
                      className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
                    >
                      {artifact.error_message.slice(0, 300)}
                    </p>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        ) : (
          <Card className="border-dashed">
            <CardContent className="p-6 text-sm text-slate-600">
              No attachments or supported links were retrieved from this
              message.
            </CardContent>
          </Card>
        )}
      </section>

      <section aria-labelledby="processing-timeline-heading" className="space-y-3">
        <h2
          id="processing-timeline-heading"
          className="text-base font-semibold text-slate-900"
        >
          Processing timeline
        </h2>
        {data.events.length > 0 ? (
          <Card>
            <CardContent className="p-5">
              <ol className="relative space-y-6 border-l border-slate-200 pl-6">
                {data.events.map((event) => (
                  <li key={event.id} className="relative">
                    <span
                      className="absolute -left-[29px] top-1.5 h-3 w-3 rounded-full border-2 border-white bg-blue-600 ring-1 ring-blue-200"
                      aria-hidden="true"
                    />
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-medium text-slate-900">
                        {event.title}
                      </h3>
                      <EmailStatusBadge status={event.status} />
                    </div>
                    {event.detail && (
                      <p className="mt-1 whitespace-pre-wrap break-words text-sm text-slate-700">
                        {event.detail}
                      </p>
                    )}
                    <p className="mt-1 text-xs text-slate-500">
                      {formatDateTime(event.created_at)}
                    </p>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
        ) : (
          <Card className="border-dashed">
            <CardContent className="p-6 text-sm text-slate-600">
              No timeline events have been recorded yet.
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  );
}

function DeadlineDecisionButtons({
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
  const actions: EmailDeadlineDecisionAction[] = activeStatus === null
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

function ProposalDecisionButtons({
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

function DraftEditor({ draft }: { draft: EmailInboxDraft }) {
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
          <Button type="button" size="sm" onClick={() => openDecision("approve")}>
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

type BriefStateSnapshot = {
  expected_status: "completed" | "review_required" | "ignored";
  expected_updated_at: string;
};

function IntelligenceFeedback({
  messageId,
  intelligence,
}: {
  messageId: string;
  intelligence: EmailIntelligenceDetail;
}) {
  const feedback = useCreateEmailIntelligenceFeedback();
  const retryAnalysis = useRetryEmailIntelligence();
  const [correctionField, setCorrectionField] =
    useState<EmailAiCorrectionField | null>(null);
  const [dismissOpen, setDismissOpen] = useState(false);
  const [correctionSnapshot, setCorrectionSnapshot] =
    useState<BriefStateSnapshot | null>(null);
  const [dismissSnapshot, setDismissSnapshot] =
    useState<BriefStateSnapshot | null>(null);
  const [correctionText, setCorrectionText] = useState("");
  const [correctionNote, setCorrectionNote] = useState("");
  const [selectedIntent, setSelectedIntent] = useState(
    intelligence.intent ?? "other",
  );
  const [selectedPriority, setSelectedPriority] = useState<
    "low" | "normal" | "high" | "urgent"
  >(
    isEmailPriority(intelligence.priority)
      ? intelligence.priority
      : "normal",
  );
  const [selectedGroupId, setSelectedGroupId] = useState(
    intelligence.linked_group_id ?? "",
  );
  const [selectedPassengerIds, setSelectedPassengerIds] = useState<string[]>(
    intelligence.linked_passenger_ids,
  );
  const [selectedDeadlineId, setSelectedDeadlineId] = useState("");
  const [deadlineValue, setDeadlineValue] = useState("");
  const [notificationExpected, setNotificationExpected] = useState(true);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const isLinkCorrection = correctionField === "linked_group"
    || correctionField === "linked_passengers";
  const groups = useEmailReviewOptions(
    undefined,
    isLinkCorrection,
    messageId,
  );
  const passengers = useEmailReviewOptions(
    selectedGroupId || undefined,
    correctionField === "linked_passengers" && Boolean(selectedGroupId),
    messageId,
  );
  const isDismissed = intelligence.status === "ignored";
  const isConfirmed = intelligence.human_review_confirmed;
  const canReview = ["completed", "review_required"].includes(
    intelligence.status,
  );
  const canCorrect = canReview || isDismissed;
  const isFailed = intelligence.status === "failed";

  function currentBriefState(): BriefStateSnapshot | null {
    if (
      intelligence.status !== "completed"
      && intelligence.status !== "review_required"
      && intelligence.status !== "ignored"
    ) {
      return null;
    }
    return {
      expected_status: intelligence.status,
      expected_updated_at: intelligence.updated_at,
    };
  }

  function resetCorrection() {
    setCorrectionField(null);
    setCorrectionSnapshot(null);
    setCorrectionText("");
    setCorrectionNote("");
    setSelectedIntent(intelligence.intent ?? "other");
    setSelectedPriority(
      isEmailPriority(intelligence.priority)
        ? intelligence.priority
        : "normal",
    );
    setSelectedGroupId(intelligence.linked_group_id ?? "");
    setSelectedPassengerIds(intelligence.linked_passenger_ids);
    setSelectedDeadlineId("");
    setDeadlineValue("");
    setNotificationExpected(true);
  }

  function openCorrection(option: FeedbackCorrectionOption) {
    const snapshot = currentBriefState();
    if (!snapshot) return;
    feedback.reset();
    setSuccessMessage(null);
    resetCorrection();
    setNotificationExpected(option.notificationExpected ?? true);
    setCorrectionText(
      option.field === "summary" ? intelligence.summary ?? "" : "",
    );
    if (option.field === "deadline" && intelligence.deadlines.length === 1) {
      const [onlyDeadline] = intelligence.deadlines;
      setSelectedDeadlineId(onlyDeadline.id);
      setDeadlineValue(toLocalDateTimeInput(onlyDeadline.due_at));
    }
    setCorrectionSnapshot(snapshot);
    setCorrectionField(option.field);
  }

  function sendConfirmation() {
    const expected = currentBriefState();
    if (!expected) return;
    setSuccessMessage(null);
    feedback.reset();
    feedback.mutate(
      {
        analysisId: intelligence.id,
        request: {
          feedback_type: "confirmation",
          field_name: "analysis",
          ...expected,
        },
      },
      {
        onSuccess: () => {
          setSuccessMessage("Review confirmed. Any separate action cards remain open.");
        },
      },
    );
  }

  function sendDismissal() {
    const expected = dismissSnapshot;
    if (!expected) return;
    feedback.mutate(
      {
        analysisId: intelligence.id,
        request: {
          feedback_type: "dismissal",
          field_name: "analysis",
          ...expected,
        },
      },
      {
        onSuccess: () => {
          setDismissOpen(false);
          setDismissSnapshot(null);
          setSuccessMessage(
            "AI brief dismissed and removed from active AI views. The source email was not changed.",
          );
        },
      },
    );
  }

  function submitCorrection() {
    const expected = correctionSnapshot;
    if (
      correctionField === null
      || expected === null
      || !isCorrectionReady({
        field: correctionField,
        correctionText,
        selectedIntent,
        selectedGroupId,
        selectedDeadlineId,
        hasExistingDeadlines: intelligence.deadlines.length > 0,
        deadlineValue,
      })
    ) {
      return;
    }
    const correction: EmailAiCorrectionValue = (() => {
      if (correctionField === "summary") {
        return { text: correctionText.trim() };
      }
      if (correctionField === "intent") {
        return { intent: selectedIntent };
      }
      if (correctionField === "priority") {
        return { priority: selectedPriority };
      }
      if (correctionField === "linked_group") {
        return { group_id: selectedGroupId };
      }
      if (correctionField === "linked_passengers") {
        return { passenger_ids: selectedPassengerIds };
      }
      if (correctionField === "deadline") {
        return {
          deadline_id: selectedDeadlineId || undefined,
          due_at: new Date(deadlineValue).toISOString(),
        };
      }
      return { notification_expected: notificationExpected };
    })();
    feedback.mutate(
      {
        analysisId: intelligence.id,
        request: {
          feedback_type: "correction",
          field_name: correctionField,
          ...expected,
          correction,
          note: correctionNote.trim() || undefined,
        },
      },
      {
        onSuccess: () => {
          resetCorrection();
          setSuccessMessage(
            "Correction applied to this brief and recorded in its audit trail.",
          );
        },
      },
    );
  }

  return (
    <Card className="border-dashed">
      <CardContent className="space-y-3 p-5">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">
            Improve this analysis
          </h3>
          <p className="mt-1 text-xs text-slate-500">
            Feedback is stored for this owner-scoped analysis and does not
            change the source email.
          </p>
        </div>
        {isDismissed && (
          <EmailNotice tone="info">
            This AI brief is currently ignored. You can still report a missed
            match, deadline, or classification; the source email will not be
            changed.
          </EmailNotice>
        )}
        {isConfirmed && (
          <EmailNotice tone="success">
            You confirmed this AI brief. Corrections and dismissal remain
            auditable if the operational facts change.
          </EmailNotice>
        )}
        {!canCorrect && !isFailed && (
          <EmailNotice tone="info">
            Feedback becomes available after the AI brief finishes.
          </EmailNotice>
        )}
        {isFailed && (
          <EmailNotice tone="error">
            This AI brief could not be completed. Retry starts a fresh bounded
            attempt cycle and does not change the source email.
          </EmailNotice>
        )}
        {successMessage && (
          <EmailNotice tone="success">{successMessage}</EmailNotice>
        )}
        {retryAnalysis.isError && (
          <EmailNotice tone="error">
            {readActionError(
              retryAnalysis.error,
              "The AI brief could not be queued for retry.",
            )}
          </EmailNotice>
        )}
        {feedback.isError && correctionField === null && !dismissOpen && (
          <EmailNotice tone="error">
            {readActionError(feedback.error, "Feedback could not be saved.")}
          </EmailNotice>
        )}
        {canCorrect && (
          <div className="flex flex-wrap gap-2">
            {canReview && !isConfirmed && (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={feedback.isPending}
                onClick={sendConfirmation}
              >
                Looks right
              </Button>
            )}
            {feedbackCorrectionOptions(intelligence).map((option) => (
              <Button
                key={`${option.field}-${option.buttonLabel}`}
                type="button"
                size="sm"
                variant="secondary"
                disabled={feedback.isPending}
                onClick={() => openCorrection(option)}
              >
                {option.buttonLabel}
              </Button>
            ))}
            {canReview && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={feedback.isPending}
                onClick={() => {
                  const snapshot = currentBriefState();
                  if (!snapshot) return;
                  feedback.reset();
                  setDismissSnapshot(snapshot);
                  setDismissOpen(true);
                }}
              >
                Not useful
              </Button>
            )}
          </div>
        )}
        {isFailed && (
          <Button
            type="button"
            size="sm"
            variant="secondary"
            leftIcon={<RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />}
            isLoading={retryAnalysis.isPending}
            onClick={() => {
              setSuccessMessage(null);
              retryAnalysis.reset();
              retryAnalysis.mutate(intelligence.id, {
                onSuccess: (response) => {
                  setSuccessMessage(response.message);
                },
              });
            }}
          >
            Retry analysis
          </Button>
        )}

        {correctionField && (
          <EmailDialog
            title={feedbackCorrectionCopy(correctionField).title}
            description="The correction updates this operational brief immediately and is recorded in its audit trail. It never changes or sends the source email."
            isBusy={feedback.isPending}
            onClose={() => {
              if (feedback.isPending) return;
              resetCorrection();
              feedback.reset();
            }}
          >
            <div className="space-y-4">
              {correctionField === "summary" && (
                <label className="block text-sm font-medium text-slate-700">
                  Corrected summary
                  <textarea
                    required
                    value={correctionText}
                    maxLength={2000}
                    rows={6}
                    className="mt-1.5 w-full resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none transition-colors focus:border-transparent focus:ring-2 focus:ring-blue-600"
                    onChange={(event) =>
                      setCorrectionText(event.target.value)}
                  />
                </label>
              )}
              {correctionField === "intent" && (
                <label className="block text-sm font-medium text-slate-700">
                  Correct category
                  <select
                    value={selectedIntent}
                    disabled={feedback.isPending}
                    onChange={(event) =>
                      setSelectedIntent(event.target.value)}
                    className="mt-1.5 block h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:bg-slate-100"
                  >
                    {EMAIL_INTENT_OPTIONS.map((intent) => (
                      <option key={intent} value={intent}>
                        {formatEmailLabel(intent)}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {correctionField === "priority" && (
                <label className="block text-sm font-medium text-slate-700">
                  Correct priority
                  <select
                    value={selectedPriority}
                    disabled={feedback.isPending}
                    onChange={(event) =>
                      setSelectedPriority(
                        event.target.value as
                          | "low"
                          | "normal"
                          | "high"
                          | "urgent",
                      )}
                    className="mt-1.5 block h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:bg-slate-100"
                  >
                    {(["low", "normal", "high", "urgent"] as const).map(
                      (priority) => (
                        <option key={priority} value={priority}>
                          {formatEmailLabel(priority)}
                        </option>
                      ),
                    )}
                  </select>
                </label>
              )}
              {(correctionField === "linked_group"
                || correctionField === "linked_passengers") && (
                <label className="block text-sm font-medium text-slate-700">
                  Correct group
                  <select
                    value={selectedGroupId}
                    disabled={
                      groups.isLoading
                      || groups.isError
                      || feedback.isPending
                    }
                    onChange={(event) => {
                      setSelectedGroupId(event.target.value);
                      setSelectedPassengerIds([]);
                    }}
                    className="mt-1.5 block h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:bg-slate-100"
                  >
                    <option value="">Select a visible group</option>
                    {groups.data?.groups.map((group) => (
                      <option key={group.id} value={group.id}>
                        {group.name}
                        {group.destination ? ` — ${group.destination}` : ""}
                        {group.travel_date ? ` — ${group.travel_date}` : ""}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {correctionField === "linked_passengers" && (
                <fieldset
                  disabled={
                    !selectedGroupId
                    || passengers.isLoading
                    || passengers.isError
                    || feedback.isPending
                  }
                  className="space-y-2"
                >
                  <legend className="text-sm font-medium text-slate-700">
                    Correct passengers
                  </legend>
                  <p className="text-xs text-slate-500">
                    Select every passenger referenced by this email. Leave all
                    unselected to remove the current passenger links.
                  </p>
                  <div className="max-h-56 space-y-2 overflow-y-auto rounded-lg border border-slate-200 p-3">
                    {passengers.data?.passengers.length ? (
                      passengers.data.passengers.map((passenger) => (
                        <label
                          key={passenger.id}
                          className="flex items-start gap-2 text-sm text-slate-700"
                        >
                          <input
                            type="checkbox"
                            checked={selectedPassengerIds.includes(passenger.id)}
                            className="mt-0.5 h-4 w-4 rounded border-slate-300"
                            onChange={(event) =>
                              setSelectedPassengerIds((current) =>
                                event.target.checked
                                  ? [...current, passenger.id]
                                  : current.filter(
                                      (id) => id !== passenger.id,
                                    ),
                              )}
                          />
                          <span>{passenger.name}</span>
                        </label>
                      ))
                    ) : (
                      <p className="text-sm text-slate-500">
                        {selectedGroupId
                          ? "No available passengers were found in this group."
                          : "Select a group to load its passengers."}
                      </p>
                    )}
                  </div>
                </fieldset>
              )}
              {correctionField === "deadline" && (
                <div className="space-y-4">
                  {intelligence.deadlines.length > 0 && (
                    <label className="block text-sm font-medium text-slate-700">
                      Deadline to correct
                      <select
                        required
                        value={selectedDeadlineId}
                        disabled={feedback.isPending}
                        onChange={(event) => {
                          const deadlineId = event.target.value;
                          const selected = intelligence.deadlines.find(
                            (deadline) => deadline.id === deadlineId,
                          );
                          setSelectedDeadlineId(deadlineId);
                          setDeadlineValue(
                            toLocalDateTimeInput(selected?.due_at),
                          );
                        }}
                        className="mt-1.5 block h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:bg-slate-100"
                      >
                        <option value="">Select a detected deadline</option>
                        {intelligence.deadlines.map((deadline) => (
                          <option key={deadline.id} value={deadline.id}>
                            {deadline.source_phrase}
                            {" — "}
                            {deadline.due_at
                              ? formatDateTime(deadline.due_at)
                              : "No date detected"}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <label className="block text-sm font-medium text-slate-700">
                    Correct date and time
                    <input
                      type="datetime-local"
                      required
                      value={deadlineValue}
                      disabled={feedback.isPending}
                      onChange={(event) => setDeadlineValue(event.target.value)}
                      className="mt-1.5 block h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:bg-slate-100"
                    />
                    <span className="mt-1 block text-xs font-normal text-slate-500">
                      Interpreted in your device timezone and stored as an exact
                      UTC instant.
                    </span>
                  </label>
                </div>
              )}
              {correctionField === "notification" && (
                <fieldset className="space-y-2">
                  <legend className="text-sm font-medium text-slate-700">
                    Expected notification
                  </legend>
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input
                      type="radio"
                      name="notification-expected"
                      checked={notificationExpected}
                      onChange={() => setNotificationExpected(true)}
                    />
                    This email should notify me
                  </label>
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input
                      type="radio"
                      name="notification-expected"
                      checked={!notificationExpected}
                      onChange={() => setNotificationExpected(false)}
                    />
                    This email should not notify me
                  </label>
                </fieldset>
              )}
              <label className="block text-sm font-medium text-slate-700">
                Note <span className="font-normal text-slate-500">(optional)</span>
                <textarea
                  value={correctionNote}
                  maxLength={1000}
                  rows={3}
                  className="mt-1.5 w-full resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none transition-colors focus:border-transparent focus:ring-2 focus:ring-blue-600"
                  onChange={(event) => setCorrectionNote(event.target.value)}
                />
              </label>
              {(
                (correctionField === "linked_group"
                  || correctionField === "linked_passengers")
                && (groups.isError || passengers.isError)
              ) && (
                <EmailNotice tone="error">
                  Visible group or passenger choices could not be loaded.
                  Close this dialog and try again.
                </EmailNotice>
              )}
              {feedback.isError && (
                <EmailNotice tone="error">
                  {readActionError(
                    feedback.error,
                    "The correction could not be saved.",
                  )}
                </EmailNotice>
              )}
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  disabled={feedback.isPending}
                  onClick={() => {
                    resetCorrection();
                    feedback.reset();
                  }}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  isLoading={feedback.isPending}
                  disabled={
                    !isCorrectionReady({
                      field: correctionField,
                      correctionText,
                      selectedIntent,
                      selectedGroupId,
                      selectedDeadlineId,
                      hasExistingDeadlines:
                        intelligence.deadlines.length > 0,
                      deadlineValue,
                    })
                    || (
                      (
                        correctionField === "linked_group"
                        || correctionField === "linked_passengers"
                      )
                      && groups.isError
                    )
                    || (
                      correctionField === "linked_passengers"
                      && passengers.isError
                    )
                  }
                  onClick={submitCorrection}
                >
                  Save correction
                </Button>
              </div>
            </div>
          </EmailDialog>
        )}
        {dismissOpen && (
          <EmailDialog
            title="Dismiss this AI brief?"
            description="This removes the brief and its open proposals, deadlines, and drafts from active AI views. It does not alter or send the source email."
            isBusy={feedback.isPending}
            onClose={() => {
              if (feedback.isPending) return;
              setDismissOpen(false);
              setDismissSnapshot(null);
              feedback.reset();
            }}
          >
            <div className="space-y-4">
              <EmailNotice tone="warning">
                Use this only when the full brief is not useful. Individual
                corrections can be recorded without closing the work.
              </EmailNotice>
              {feedback.isError && (
                <EmailNotice tone="error">
                  {readActionError(
                    feedback.error,
                    "The AI brief could not be dismissed.",
                  )}
                </EmailNotice>
              )}
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  disabled={feedback.isPending}
                  onClick={() => {
                    setDismissOpen(false);
                    setDismissSnapshot(null);
                    feedback.reset();
                  }}
                >
                  Keep brief
                </Button>
                <Button
                  type="button"
                  variant="danger"
                  isLoading={feedback.isPending}
                  onClick={sendDismissal}
                >
                  Dismiss AI brief
                </Button>
              </div>
            </div>
          </EmailDialog>
        )}
      </CardContent>
    </Card>
  );
}

function proposalActionLabel(action: EmailProposalDecisionAction) {
  if (action === "approve") return "Approve";
  if (action === "reject") return "Reject";
  return "Dismiss";
}

interface FeedbackCorrectionOption {
  field: EmailAiCorrectionField;
  buttonLabel: string;
  notificationExpected?: boolean;
}

function feedbackCorrectionOptions(intelligence: EmailIntelligenceDetail) {
  const options: FeedbackCorrectionOption[] = [
    { field: "summary", buttonLabel: "Correct summary" },
    { field: "intent", buttonLabel: "Wrong category" },
    { field: "priority", buttonLabel: "Wrong priority" },
  ];
  options.push({
    field: "linked_group",
    buttonLabel: intelligence.linked_group_name
      ? "Wrong group"
      : "Add missing group",
  });
  options.push({
    field: "linked_passengers",
    buttonLabel: intelligence.linked_passengers.length
      ? "Wrong passenger"
      : "Add missing passenger",
  });
  options.push({
    field: "deadline",
    buttonLabel: intelligence.deadlines.length
      ? "Wrong deadline"
      : "Add missing deadline",
  });
  options.push(
    {
      field: "notification",
      buttonLabel: "Should have notified me",
      notificationExpected: true,
    },
    {
      field: "notification",
      buttonLabel: "Should not notify me",
      notificationExpected: false,
    },
  );
  return options;
}

function feedbackCorrectionCopy(field: EmailAiCorrectionField) {
  const copy: Record<
    EmailAiCorrectionField,
    { title: string }
  > = {
    summary: {
      title: "Correct the operational summary",
    },
    linked_group: {
      title: "Select the correct group",
    },
    linked_passengers: {
      title: "Select the correct passengers",
    },
    intent: {
      title: "Correct the email category",
    },
    priority: {
      title: "Correct the priority",
    },
    deadline: {
      title: "Correct the deadline",
    },
    notification: {
      title: "Correct the notification expectation",
    },
  };
  return copy[field];
}

const EMAIL_INTENT_OPTIONS = [
  "document_submission",
  "document_request",
  "itinerary_update",
  "itinerary_change",
  "visa_status",
  "information_request",
  "action_request",
  "deadline_notice",
  "deadline_update",
  "cancellation",
  "payment",
  "general_travel",
  "other",
] as const;

function isEmailPriority(
  value: string | null,
): value is "low" | "normal" | "high" | "urgent" {
  return value !== null
    && ["low", "normal", "high", "urgent"].includes(value);
}

function isCorrectionReady({
  field,
  correctionText,
  selectedIntent,
  selectedGroupId,
  selectedDeadlineId,
  hasExistingDeadlines,
  deadlineValue,
}: {
  field: EmailAiCorrectionField;
  correctionText: string;
  selectedIntent: string;
  selectedGroupId: string;
  selectedDeadlineId: string;
  hasExistingDeadlines: boolean;
  deadlineValue: string;
}) {
  if (field === "summary") return Boolean(correctionText.trim());
  if (field === "intent") return Boolean(selectedIntent);
  if (field === "linked_group" || field === "linked_passengers") {
    return Boolean(selectedGroupId);
  }
  if (field === "deadline") {
    return (
      (!hasExistingDeadlines || Boolean(selectedDeadlineId))
      && Boolean(deadlineValue)
      && !Number.isNaN(Date.parse(deadlineValue))
    );
  }
  return true;
}

function toLocalDateTimeInput(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function isActiveDeadlineStatus(
  value: string,
): value is EmailActiveDeadlineStatus {
  return ["detected", "review_required", "acknowledged"].includes(value);
}

function deadlineActionLabel(action: EmailDeadlineDecisionAction) {
  if (action === "acknowledge") return "Acknowledge";
  if (action === "complete") return "Mark complete";
  return "Dismiss";
}

function readActionError(error: unknown, fallback: string) {
  if (
    typeof error === "object"
    && error !== null
    && "message" in error
    && typeof error.message === "string"
  ) {
    return error.message.slice(0, 300);
  }
  return fallback;
}
