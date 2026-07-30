"use client";

import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  FileEdit,
  Hourglass,
  Inbox,
  Mail,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Badge, Button, Card, CardContent } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import {
  formatConfidence,
  formatDateTime,
  formatRelativeTime,
} from "@/lib/utils/format";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { useEmailOperationalInbox } from "../hooks/use-email-integrations";
import type {
  EmailOperationalInboxItem,
  EmailOperationalInboxView,
} from "../types";
import { formatEmailLabel } from "../utils/email-integrations";
import {
  EmailCardSkeletons,
  EmailNotice,
  EmailQueryError,
  EmailStatusBadge,
} from "./email-integrations-ui";

const INBOX_VIEWS: ReadonlyArray<{
  value: EmailOperationalInboxView;
  label: string;
  description: string;
  icon: LucideIcon;
}> = [
  {
    value: "needs_attention",
    label: "Needs attention",
    description: "Approvals, failures, uncertain matches, and required replies",
    icon: AlertTriangle,
  },
  {
    value: "upcoming_deadlines",
    label: "Deadlines",
    description: "Upcoming and overdue operational commitments",
    icon: Clock3,
  },
  {
    value: "drafts_ready",
    label: "Drafts ready",
    description: "Prepared replies that still require manual review",
    icon: FileEdit,
  },
  {
    value: "waiting",
    label: "Waiting",
    description: "Analysis still being prepared or awaiting completion",
    icon: Hourglass,
  },
  {
    value: "completed_automatically",
    label: "Analysis complete",
    description: "AI review finished with no open decisions or prepared work",
    icon: CheckCircle2,
  },
  {
    value: "all_activity",
    label: "All activity",
    description: "Every retained operational email outcome",
    icon: Inbox,
  },
];

export function EmailOperationalInboxPage() {
  const user = useAuthStore(selectUser);
  const [view, setView] =
    useState<EmailOperationalInboxView>("needs_attention");
  const inbox = useEmailOperationalInbox(user?.id, view);
  const items = useMemo(
    () => inbox.data?.pages.flatMap((page) => page.items) ?? [],
    [inbox.data],
  );
  const counts = inbox.data?.pages[0]?.counts;
  const activeView = INBOX_VIEWS.find((option) => option.value === view);

  return (
    <div className="space-y-6">
      <div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">
              AI-assisted travel operations
            </p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-950">
              Operations Inbox
            </h1>
            <p className="mt-1 max-w-3xl text-sm text-slate-600">
              See what changed, what needs a decision, and what the platform
              has prepared from your personally connected accounts.
            </p>
          </div>
          <Link
            href={ROUTES.dashboard.emailIntegrations as never}
            className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
          >
            <Mail className="h-4 w-4" aria-hidden="true" />
            Connected accounts
          </Link>
        </div>
      </div>

      <EmailNotice tone="info">
        Prepared drafts can be reviewed and edited here, but sending remains
        manual. The platform cannot send, edit, or delete mail in connected
        Gmail or Outlook accounts.
      </EmailNotice>

      <div
        className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3"
        aria-label="Operations inbox views"
      >
        {INBOX_VIEWS.map((option) => {
          const Icon = option.icon;
          const isActive = option.value === view;
          const count = counts?.[option.value];
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={isActive}
              className={`rounded-xl border p-4 text-left transition-colors ${
                isActive
                  ? "border-blue-300 bg-blue-50 ring-1 ring-blue-200"
                  : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
              }`}
              onClick={() => setView(option.value)}
            >
              <span className="flex items-center justify-between gap-3">
                <span
                  className={`flex h-8 w-8 items-center justify-center rounded-lg ${
                    isActive
                      ? "bg-blue-600 text-white"
                      : "bg-slate-100 text-slate-600"
                  }`}
                >
                  <Icon className="h-4 w-4" aria-hidden="true" />
                </span>
                {typeof count === "number" && (
                  <span className="text-lg font-bold text-slate-950">
                    {count.toLocaleString()}
                  </span>
                )}
              </span>
              <span className="mt-3 block text-sm font-semibold text-slate-900">
                {option.label}
              </span>
              <span className="mt-1 block text-xs leading-5 text-slate-500">
                {option.description}
              </span>
            </button>
          );
        })}
      </div>

      <section aria-labelledby="operations-inbox-results-heading">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <h2
              id="operations-inbox-results-heading"
              className="text-base font-semibold text-slate-900"
            >
              {activeView?.label ?? "Operational email activity"}
            </h2>
            <p className="mt-0.5 text-sm text-slate-500">
              {activeView?.description}
            </p>
          </div>
          {inbox.isFetching && !inbox.isLoading && (
            <span role="status" className="text-xs text-slate-500">
              Refreshing…
            </span>
          )}
        </div>

        {inbox.isLoading ? (
          <EmailCardSkeletons />
        ) : inbox.isError ? (
          <EmailQueryError
            title="The operations inbox could not be loaded."
            onRetry={() => void inbox.refetch()}
          />
        ) : items.length > 0 ? (
          <ol className="space-y-4">
            {items.map((item) => (
              <OperationalInboxCard key={item.analysis_id} item={item} />
            ))}
          </ol>
        ) : (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center px-6 py-12 text-center">
              <span className="rounded-full bg-slate-100 p-3 text-slate-600">
                <Inbox className="h-6 w-6" aria-hidden="true" />
              </span>
              <h3 className="mt-4 font-semibold text-slate-900">
                Nothing in {activeView?.label.toLowerCase() ?? "this view"}
              </h3>
              <p className="mt-1 max-w-lg text-sm text-slate-600">
                New account-scoped operational items will appear after a
                connected inbox synchronizes and analysis completes.
              </p>
            </CardContent>
          </Card>
        )}

        {inbox.hasNextPage && (
          <div className="mt-4 flex justify-center">
            <Button
              type="button"
              variant="secondary"
              isLoading={inbox.isFetchingNextPage}
              onClick={() => void inbox.fetchNextPage()}
            >
              Load older items
            </Button>
          </div>
        )}
      </section>
    </div>
  );
}

function OperationalInboxCard({ item }: { item: EmailOperationalInboxItem }) {
  const hasPreparedWork =
    item.proposal_count > 0 || Boolean(item.draft_status);
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
            <InboxDefinition term="Connected inbox">
              {formatEmailLabel(item.provider)} · {item.account_email}
            </InboxDefinition>
            <InboxDefinition term="Received">
              {formatDateTime(item.received_at)}
            </InboxDefinition>
            <InboxDefinition term="Linked group">
              {item.group_name ?? "Not confidently linked"}
            </InboxDefinition>
            <InboxDefinition term="Analysis confidence">
              {formatConfidence(item.confidence)}
            </InboxDefinition>
          </dl>

          <div className="grid gap-4 lg:grid-cols-2">
            <div
              className={`rounded-lg border p-4 ${
                deadline
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
              className={`rounded-lg border p-4 ${
                hasPreparedWork
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
              href={ROUTES.dashboard.emailIntegrationMessage(
                item.message_id,
              ) as never}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white shadow-sm hover:bg-blue-700"
            >
              Review operational detail
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
            {item.group_id && (
              <Link
                href={ROUTES.dashboard.passportGroup(item.group_id) as never}
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

function PriorityBadge({ priority }: { priority: string }) {
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

function InboxDefinition({
  term,
  children,
}: {
  term: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {term}
      </dt>
      <dd className="mt-1 break-words text-sm text-slate-800">{children}</dd>
    </div>
  );
}
