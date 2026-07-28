"use client";

import Link from "next/link";
import { ArrowRight, Inbox } from "lucide-react";
import { Card, CardContent } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { formatDateTime } from "@/lib/utils/format";
import { useEmailActivity } from "../hooks/use-email-integrations";
import {
  Definition,
  EmailCardSkeletons,
  EmailQueryError,
  EmailStatusBadge,
} from "./email-integrations-ui";

export function EmailActivityPage() {
  const activity = useEmailActivity();

  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-950">
          Email processing activity
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          Inspect relevant inbox messages, automated outcomes, reviews, and
          retrieval failures.
        </p>
      </div>

      {activity.isLoading ? (
        <EmailCardSkeletons />
      ) : activity.isError ? (
        <EmailQueryError
          title="Email processing activity could not be loaded."
          onRetry={() => void activity.refetch()}
        />
      ) : activity.data?.length ? (
        <ol className="space-y-4">
          {activity.data.map((item) => (
            <li key={item.message_id}>
              <Card>
                <CardContent className="space-y-4 p-5">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <EmailStatusBadge status={item.processing_status} />
                        <span className="text-xs text-slate-500">
                          {item.account_email}
                        </span>
                      </div>
                      <h2 className="mt-2 break-words font-semibold text-slate-950">
                        {item.subject || "No subject"}
                      </h2>
                      <p className="mt-1 break-all text-sm text-slate-600">
                        From {item.sender_email}
                      </p>
                    </div>
                    <Link
                      href={ROUTES.dashboard.emailIntegrationMessage(
                        item.message_id,
                      ) as never}
                      className="inline-flex shrink-0 items-center gap-1 text-sm font-medium text-blue-700 hover:text-blue-800 hover:underline"
                    >
                      View timeline
                      <ArrowRight className="h-4 w-4" aria-hidden="true" />
                    </Link>
                  </div>

                  <dl className="grid gap-4 rounded-lg bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-4">
                    <Definition term="Received">
                      {formatDateTime(item.received_at)}
                    </Definition>
                    <Definition term="Relevance">
                      <EmailStatusBadge status={item.relevance_status} />
                    </Definition>
                    <Definition term="Matched group">
                      {item.group_name ?? "Not matched"}
                    </Definition>
                    <Definition term="Connection">
                      {item.account_email}
                    </Definition>
                  </dl>

                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    <ActivityCount
                      value={item.retrieved_count}
                      label="Retrieved"
                    />
                    <ActivityCount value={item.matched_count} label="Matched" />
                    <ActivityCount value={item.review_count} label="For review" />
                    <ActivityCount
                      value={item.failure_count}
                      label="Failures"
                      hasError={item.failure_count > 0}
                    />
                  </div>
                </CardContent>
              </Card>
            </li>
          ))}
        </ol>
      ) : (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center px-6 py-12 text-center">
            <span className="rounded-full bg-slate-100 p-3 text-slate-600">
              <Inbox className="h-6 w-6" aria-hidden="true" />
            </span>
            <h2 className="mt-4 font-semibold text-slate-900">
              No email activity yet
            </h2>
            <p className="mt-1 max-w-lg text-sm text-slate-600">
              Relevant emails and their processing outcomes will appear here
              after a connected inbox synchronizes.
            </p>
          </CardContent>
        </Card>
      )}
    </main>
  );
}

function ActivityCount({
  value,
  label,
  hasError = false,
}: {
  value: number;
  label: string;
  hasError?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border px-3 py-2 ${
        hasError
          ? "border-red-200 bg-red-50"
          : "border-slate-200 bg-white"
      }`}
    >
      <p
        className={`text-lg font-semibold ${
          hasError ? "text-red-800" : "text-slate-900"
        }`}
      >
        {value.toLocaleString()}
      </p>
      <p className={`text-xs ${hasError ? "text-red-700" : "text-slate-600"}`}>
        {label}
      </p>
    </div>
  );
}
