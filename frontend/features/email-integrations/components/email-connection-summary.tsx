import { Card, CardContent, Skeleton } from "@/components/ui";
import type { EmailConnectionsController } from "../hooks/use-email-connections-controller";
import { EmailQueryError } from "./email-integrations-ui";

const SUMMARY_METRICS = [
  ["connected_accounts", "Connected accounts"],
  ["relevant_emails_today", "Relevant emails today"],
  ["documents_retrieved_today", "Documents retrieved today"],
  ["automatically_matched_today", "Automatically matched today"],
  ["revisions_detected_today", "Revisions detected today"],
  ["pending_review", "Pending review"],
  ["retrieval_failures_today", "Retrieval failures today"],
] as const;

export function EmailConnectionSummary({ summary }: Pick<EmailConnectionsController, "summary">) {
  return (
    <section aria-labelledby="email-summary-heading">
      <h2
        id="email-summary-heading"
        className="mb-3 text-base font-semibold text-slate-900"
      >
        Today&apos;s email operations
      </h2>
      {summary.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 7 }, (_, index) => (
            <Skeleton key={index} className="h-24 rounded-xl" />
          ))}
        </div>
      ) : summary.isError ? (
        <EmailQueryError
          title="Email processing totals could not be loaded."
          onRetry={() => void summary.refetch()}
        />
      ) : summary.data ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {SUMMARY_METRICS.map(([key, label]) => (
            <Card key={key}>
              <CardContent className="p-4">
                <p className="text-2xl font-bold text-slate-950">
                  {summary.data[key].toLocaleString()}
                </p>
                <p className="mt-1 text-sm text-slate-600">{label}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : null}
    </section>

  );
}
