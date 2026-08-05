"use client";

import {
  Activity,
  BarChart3,
  CalendarDays,
  CheckCircle2,
  Gauge,
  TrendingUp,
} from "lucide-react";
import {
  WorkspaceEmptyState,
  WorkspaceErrorNotice,
  WorkspaceHeaderContext,
  WorkspacePageHeader,
  WorkspaceSummaryItem,
  WorkspaceSummaryStrip,
} from "@/components/shared/workspace-ui";
import { Skeleton } from "@/components/ui/skeleton";
import { useAnalyticsSummary } from "@/features/operations/hooks/use-operations";
import { cn } from "@/lib/utils/cn";

export default function AnalyticsPage() {
  const { data, isLoading, error } = useAnalyticsSummary(30);
  const confidenceEntries = Object.entries(data?.confidence_buckets ?? {});
  const statusEntries = Object.entries(data?.status_counts ?? {});
  const submissionEntries = Object.entries(data?.submissions_by_day ?? {});
  const totalSubmissions = submissionEntries.reduce((total, [, value]) => total + value, 0);
  const maxDailySubmissions = Math.max(1, ...submissionEntries.map(([, value]) => value));
  const maxConfidenceBucket = Math.max(1, ...confidenceEntries.map(([, value]) => value));
  const maxStatusCount = Math.max(1, ...statusEntries.map(([, value]) => value));
  const leadingStatus = statusEntries.reduce<[string, number] | null>(
    (current, entry) => (!current || entry[1] > current[1] ? entry : current),
    null,
  );

  return (
    <div className="flex flex-col gap-5">
      <WorkspacePageHeader
        eyebrow="Processing intelligence"
        title="Analytics"
        description="Read passport throughput, extraction confidence, and workflow distribution across the latest 30-day operating window."
        icon={BarChart3}
        accent="violet"
        context={(
          <>
            <WorkspaceHeaderContext icon={CalendarDays}>Last 30 days</WorkspaceHeaderContext>
            <WorkspaceHeaderContext icon={Activity}>Permission-scoped data</WorkspaceHeaderContext>
          </>
        )}
      />

      {error && (
        <WorkspaceErrorNotice>
          Analytics are unavailable for this account. No operational data or access scope has been changed.
        </WorkspaceErrorNotice>
      )}

      <WorkspaceSummaryStrip label="Analytics operating summary">
        {isLoading ? (
          Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-[72px] rounded-none" />
          ))
        ) : (
          <>
            <WorkspaceSummaryItem
              label="Submissions"
              value={totalSubmissions.toLocaleString()}
              helper="30-day volume"
              icon={TrendingUp}
              tone="info"
            />
            <WorkspaceSummaryItem
              label="Average confidence"
              value={formatConfidence(data?.average_confidence)}
              helper="extraction quality"
              icon={Gauge}
              tone="success"
            />
            <WorkspaceSummaryItem
              label="Active days"
              value={submissionEntries.filter(([, value]) => value > 0).length.toLocaleString()}
              helper="with intake"
              icon={CalendarDays}
            />
            <WorkspaceSummaryItem
              label="Leading status"
              value={leadingStatus ? toLabel(leadingStatus[0]) : "No data"}
              helper={leadingStatus ? `${leadingStatus[1].toLocaleString()} records` : undefined}
              icon={CheckCircle2}
            />
          </>
        )}
      </WorkspaceSummaryStrip>

      <div className="grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
        <section
          className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
          aria-labelledby="confidence-quality-heading"
        >
          <div className="border-b border-slate-200 bg-slate-50/70 px-4 py-3.5 sm:px-5">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-violet-600">
              Extraction health
            </p>
            <h2 id="confidence-quality-heading" className="mt-0.5 font-semibold text-slate-950">
              Confidence quality
            </h2>
          </div>
          {isLoading ? (
            <div className="space-y-3 p-5">
              <Skeleton className="h-20 w-full rounded-xl" />
              {Array.from({ length: 3 }).map((_, index) => (
                <Skeleton key={index} className="h-11 w-full rounded-lg" />
              ))}
            </div>
          ) : confidenceEntries.length === 0 && data?.average_confidence == null ? (
            <WorkspaceEmptyState
              title="No confidence sample in this window"
              description="Extraction-quality buckets will appear after passports are processed during the selected 30-day period."
            />
          ) : (
            <div className="p-5">
              <div className="rounded-xl border border-violet-100 bg-violet-50/60 px-4 py-3">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-violet-700">
                  Average extraction confidence
                </p>
                <p className="mt-1 text-2xl font-semibold tabular-nums text-slate-950">
                  {formatConfidence(data?.average_confidence)}
                </p>
              </div>
              <div className="mt-5 space-y-3">
                {confidenceEntries.map(([bucket, value]) => (
                  <DistributionBar
                    key={bucket}
                    label={toLabel(bucket)}
                    value={value}
                    max={maxConfidenceBucket}
                    tone="violet"
                  />
                ))}
              </div>
            </div>
          )}
        </section>

        <section
          className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
          aria-labelledby="status-distribution-heading"
        >
          <div className="border-b border-slate-200 bg-slate-50/70 px-4 py-3.5 sm:px-5">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-blue-600">
              Workflow composition
            </p>
            <h2 id="status-distribution-heading" className="mt-0.5 font-semibold text-slate-950">
              Status distribution
            </h2>
          </div>
          {isLoading ? (
            <div className="grid gap-3 p-5 sm:grid-cols-2">
              {Array.from({ length: 6 }).map((_, index) => (
                <Skeleton key={index} className="h-20 rounded-xl" />
              ))}
            </div>
          ) : statusEntries.length === 0 ? (
            <WorkspaceEmptyState
              title="No workflow statuses in this window"
              description="Status distribution will populate as passport records move through processing and review."
            />
          ) : (
            <div className="grid gap-px bg-slate-100 sm:grid-cols-2">
              {statusEntries.map(([status, value]) => (
                <div key={status} className="bg-white p-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-2 text-sm font-medium text-slate-700">
                      <span className={cn("h-2.5 w-2.5 rounded-full", statusDot(status))} aria-hidden="true" />
                      {toLabel(status)}
                    </span>
                    <span className="font-semibold tabular-nums text-slate-950">{value.toLocaleString()}</span>
                  </div>
                  <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
                    <div
                      className={cn("h-full rounded-full", statusBar(status))}
                      style={{ width: `${Math.max(value > 0 ? 5 : 0, (value / maxStatusCount) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        aria-labelledby="daily-submissions-heading"
      >
        <div className="flex flex-col gap-1 border-b border-slate-200 bg-slate-50/70 px-4 py-3.5 sm:px-5">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            Throughput timeline
          </p>
          <h2 id="daily-submissions-heading" className="font-semibold text-slate-950">
            Daily submissions
          </h2>
        </div>
        {isLoading ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 8 }).map((_, index) => (
              <Skeleton key={index} className="h-8 w-full rounded-lg" />
            ))}
          </div>
        ) : submissionEntries.length === 0 ? (
          <WorkspaceEmptyState
            title="No submission timeline yet"
            description="Daily volume will appear after passport intake begins in the current analytics window."
          />
        ) : (
          <div className="space-y-2 p-4 sm:p-5">
            {submissionEntries.map(([day, value]) => (
              <div
                key={day}
                className="grid grid-cols-[6.5rem_minmax(0,1fr)_3.5rem] items-center gap-3 text-sm sm:grid-cols-[8rem_minmax(0,1fr)_4rem]"
              >
                <span className="truncate text-slate-600">{day}</span>
                <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-blue-600 transition-[width] duration-200"
                    style={{ width: `${Math.max(value > 0 ? 2 : 0, (value / maxDailySubmissions) * 100)}%` }}
                  />
                </div>
                <span className="text-right font-semibold tabular-nums text-slate-900">
                  {value.toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function DistributionBar({
  label,
  value,
  max,
  tone,
}: {
  label: string;
  value: number;
  max: number;
  tone: "violet";
}) {
  return (
    <div>
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="text-slate-600">{label}</span>
        <span className="font-semibold tabular-nums text-slate-900">{value.toLocaleString()}</span>
      </div>
      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-100">
        <div
          className={cn("h-full rounded-full", tone === "violet" && "bg-violet-500")}
          style={{ width: `${Math.max(value > 0 ? 4 : 0, (value / max) * 100)}%` }}
        />
      </div>
    </div>
  );
}

function formatConfidence(value: number | null | undefined) {
  return value == null ? "N/A" : `${Math.round(value * 100)}%`;
}

function statusDot(status: string) {
  if (/confirm|complete|success|approved/.test(status)) return "bg-emerald-500";
  if (/fail|reject|error/.test(status)) return "bg-red-500";
  if (/pending|review|processing/.test(status)) return "bg-amber-500";
  return "bg-blue-500";
}

function statusBar(status: string) {
  if (/confirm|complete|success|approved/.test(status)) return "bg-emerald-500";
  if (/fail|reject|error/.test(status)) return "bg-red-500";
  if (/pending|review|processing/.test(status)) return "bg-amber-500";
  return "bg-blue-600";
}

function toLabel(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}
