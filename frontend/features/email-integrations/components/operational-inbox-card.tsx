import { Badge, Card, CardContent } from "@/components/ui";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { ROUTES } from "@/constants/routes";
import { formatConfidence, formatDateTime, formatRelativeTime } from "@/lib/utils/format";
import type { EmailOperationalInboxItem } from "../types";
import { formatEmailLabel } from "../utils/email-integrations";
import { Definition, EmailStatusBadge } from "./email-integrations-ui";

export function OperationalInboxCard({ item }: { item: EmailOperationalInboxItem; }) {
  const hasPreparedWork = item.proposal_count > 0 || Boolean(item.draft_status);
  const deadline = item.next_deadline;
  return (
    <li>
      <Card
        className={
          ["critical", "urgent"].includes(item.priority.toLowerCase())
            ? "border-red-300"
            : item.needs_attention
              ? "border-amber-300"
              : undefined
        }
      >
        <CardContent className="space-y-5 p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <PriorityBadge priority={item.priority} />
                <EmailStatusBadge status={item.status} />
                <span className="text-xs text-slate-500">
                  {formatEmailLabel(item.intent)}
                </span>
              </div>
              <h3 className="mt-2 break-words text-base font-semibold text-slate-950">
                {item.group_name
                  ? `${item.group_name} — ${item.subject || "No subject"}`
                  : item.subject || "No subject"}
              </h3>
              <p className="mt-1 break-all text-sm text-slate-600">
                From{" "}
                {item.sender_name
                  ? `${item.sender_name} — ${item.sender_email}`
                  : item.sender_email}
              </p>
            </div>
            {deadline?.due_at && (
              <div className="shrink-0 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-right">
                <p className="text-xs font-semibold text-amber-900">
                  {formatEmailLabel(deadline.deadline_type)}
                </p>
                <time
                  dateTime={deadline.due_at}
                  title={formatDateTime(deadline.due_at)}
                  className="text-xs text-amber-800"
                >
                  {formatRelativeTime(deadline.due_at)}
                </time>
              </div>
            )}
          </div>

          <p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">
            {item.summary}
          </p>

          <dl className="grid gap-4 rounded-lg bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-4">
            <Definition term="Connected inbox">
              {formatEmailLabel(item.provider)} · {item.account_email}
            </Definition>
            <Definition term="Received">
              {formatDateTime(item.received_at)}
            </Definition>
            <Definition term="Linked group">
              {item.group_name ?? "Not confidently linked"}
            </Definition>
            <Definition term="Analysis confidence">
              {formatConfidence(item.confidence)}
            </Definition>
          </dl>

          <div className="grid gap-4 lg:grid-cols-2">
            <div
              className={`rounded-lg border p-4 ${deadline
                ? "border-amber-200 bg-amber-50/60"
                : "border-slate-200"
                }`}
            >
              <h4 className="text-sm font-semibold text-slate-900">
                Next deadline
              </h4>
              {deadline ? (
                <>
                  <p className="mt-2 text-sm text-slate-700">
                    {deadline.source_phrase}
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <EmailStatusBadge status={deadline.status} />
                    {deadline.is_ambiguous && (
                      <Badge variant="warning">Needs date review</Badge>
                    )}
                    <span className="text-xs text-slate-500">
                      {formatConfidence(deadline.confidence)} confidence
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">
                    {deadline.due_at
                      ? `${formatDateTime(deadline.due_at)} · ${deadline.source_timezone}`
                      : `Date unresolved · ${deadline.source_timezone}`}
                  </p>
                </>
              ) : (
                <p className="mt-2 text-sm text-slate-600">
                  No active deadline was detected.
                </p>
              )}
            </div>

            <div
              className={`rounded-lg border p-4 ${hasPreparedWork
                ? "border-green-200 bg-green-50/60"
                : "border-slate-200"
                }`}
            >
              <h4 className="text-sm font-semibold text-slate-900">
                Prepared for review
              </h4>
              {hasPreparedWork ? (
                <ul className="mt-2 space-y-2 text-sm text-slate-700">
                  {item.proposal_count > 0 && (
                    <li>
                      {item.proposal_count.toLocaleString()} action{" "}
                      {item.proposal_count === 1 ? "proposal" : "proposals"}
                    </li>
                  )}
                  {item.draft_status && (
                    <li>
                      Prepared draft — sending remains manual
                      <span className="ml-2 text-xs text-slate-500">
                        ({formatEmailLabel(item.draft_status)})
                      </span>
                    </li>
                  )}
                </ul>
              ) : (
                <p className="mt-2 text-sm text-slate-600">
                  No action or draft has been prepared.
                </p>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4">
            <Link
              href={
                ROUTES.dashboard.emailIntegrationMessage(
                  item.message_id,
                )
              }
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white shadow-sm hover:bg-blue-700"
            >
              Review operational detail
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
            {item.group_id && (
              <Link
                href={ROUTES.dashboard.passportGroup(item.group_id)}
                className="inline-flex h-9 items-center rounded-lg px-3 text-sm font-medium text-blue-700 hover:bg-blue-50"
              >
                Open group
              </Link>
            )}
          </div>
        </CardContent>
      </Card>
    </li>
  );
}

function PriorityBadge({ priority }: { priority: string; }) {
  const normalized = priority.toLowerCase();
  const variant =
    normalized === "critical" || normalized === "urgent"
      ? "destructive"
      : normalized === "high"
        ? "warning"
        : normalized === "medium" || normalized === "normal"
          ? "secondary"
          : "outline";
  return (
    <Badge variant={variant} dot>
      {formatEmailLabel(priority)}
    </Badge>
  );
}

