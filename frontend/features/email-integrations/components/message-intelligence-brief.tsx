import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui";
import { formatConfidence, formatDateTime } from "@/lib/utils/format";
import {
  AlertTriangle,
  CalendarClock,
  FileEdit,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import type { EmailIntelligenceDetail } from "../types";
import { formatEmailLabel } from "../utils/email-integrations";
import {
  Definition,
  EmailNotice,
  EmailStatusBadge,
} from "./email-integrations-ui";
import { DeadlineDecisionButtons } from "./message-deadline-decisions";
import { DraftEditor } from "./message-draft-editor";
import { IntelligenceFeedback } from "./message-intelligence-feedback";
import { ProposalDecisionButtons } from "./message-proposal-decisions";
export function MessageIntelligenceBrief({
  messageId,
  intelligenceDetail,
}: {
  messageId: string;
  intelligenceDetail: EmailIntelligenceDetail;
}) {
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
      proposal.requires_approval &&
      proposal.allowed_actions.includes("approve"),
  );

  return (
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
            Extracted guidance is evidence for review, not an instruction to
            send or change email.
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
              {intelligenceDetail.linked_group_name ?? "No visible group match"}
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
                ) && <Badge variant="warning">Selection needs review</Badge>}
              </div>
              <p className="mt-1 text-xs text-slate-500">
                These candidates were rechecked against records you can
                currently view. Confidence and reasoning are AI evidence, not
                proof.
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
                        <p className="text-sm text-red-900">{risk}</p>
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
                        proposal.requires_approval &&
                        proposal.allowed_actions.includes("approve")
                          ? "warning"
                          : "outline"
                      }
                    >
                      {proposal.requires_approval &&
                      proposal.allowed_actions.includes("approve")
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
                Approval records this decision only. It never sends email, and
                high-risk actions remain blocked.
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
              <Definition term="Subject">{replyDraft.subject}</Definition>
            </dl>
            <p className="whitespace-pre-wrap break-words rounded-lg border border-blue-100 bg-blue-50/60 p-4 text-sm leading-6 text-blue-950">
              {replyDraft.body_text}
            </p>
            <p className="text-xs text-blue-800">
              Prepared draft — sending remains manual. The platform cannot send
              or delete messages in connected accounts.
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
  );
}
