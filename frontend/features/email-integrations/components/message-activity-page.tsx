"use client";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import {
  formatBytes,
  formatConfidence,
  formatDateTime,
} from "@/lib/utils/format";
import { ArrowLeft, ExternalLink, FileText } from "lucide-react";
import Link from "next/link";
import {
  useEmailMessage,
  useEmailMessageIntelligence,
} from "../hooks/use-email-integrations";
import { formatEmailLabel } from "../utils/email-integrations";
import {
  Definition,
  EmailCardSkeletons,
  EmailQueryError,
  EmailStatusBadge,
} from "./email-integrations-ui";
import { MessageIntelligenceBrief } from "./message-intelligence-brief";
export function EmailMessageActivityPage({ messageId }: { messageId: string }) {
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
            <h1 className="break-words text-2xl font-semibold tracking-[-0.035em] text-slate-950 sm:text-[30px]">
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
            <Definition term="Connected inbox">{data.account_email}</Definition>
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
      {!intelligence.isLoading &&
        !intelligence.isError &&
        intelligence.data === null && (
          <Card className="border-dashed">
            <CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-semibold text-slate-900">
                  AI operational brief is not available yet
                </p>
                <p className="mt-1 text-sm text-slate-600">
                  Analysis may still be queued, or AI may not be enabled for
                  this connected inbox.
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
        <MessageIntelligenceBrief
          messageId={messageId}
          intelligenceDetail={intelligenceDetail}
        />
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

      <section
        aria-labelledby="processing-timeline-heading"
        className="space-y-3"
      >
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
