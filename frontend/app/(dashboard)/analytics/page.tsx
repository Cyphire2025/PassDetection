"use client";

import { BarChart3 } from "lucide-react";
import { PageHeader } from "@/components/shared";
import { Card, CardContent, Skeleton } from "@/components/ui";
import { useAnalyticsSummary } from "@/features/operations/hooks/use-operations";

export default function AnalyticsPage() {
  const { data, isLoading, error } = useAnalyticsSummary(30);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Analytics" description="Processing quality, volume, and status trends for the last 30 days." />
      {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">Analytics are unavailable for this account.</div>}
      <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
        <Card>
          <CardContent className="p-5">
            <div className="mb-4 flex items-center gap-2 text-slate-900">
              <BarChart3 className="h-5 w-5 text-blue-600" />
              <h2 className="text-base font-semibold">Confidence Quality</h2>
            </div>
            {isLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : (
              <div className="grid gap-3">
                <Metric label="Average Confidence" value={data?.average_confidence == null ? "N/A" : `${Math.round(data.average_confidence * 100)}%`} />
                {Object.entries(data?.confidence_buckets ?? {}).map(([bucket, value]) => (
                  <Metric key={bucket} label={toLabel(bucket)} value={String(value)} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <h2 className="mb-4 text-base font-semibold text-slate-900">Status Distribution</h2>
            {isLoading ? (
              <Skeleton className="h-56 w-full" />
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {Object.entries(data?.status_counts ?? {}).map(([status, value]) => (
                  <Metric key={status} label={toLabel(status)} value={String(value)} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="p-5">
          <h2 className="mb-4 text-base font-semibold text-slate-900">Daily Submissions</h2>
          {isLoading ? (
            <Skeleton className="h-56 w-full" />
          ) : (
            <div className="grid gap-2">
              {Object.entries(data?.submissions_by_day ?? {}).map(([day, value]) => (
                <div key={day} className="grid grid-cols-[8rem_1fr_3rem] items-center gap-3 text-sm">
                  <span className="text-slate-500">{day}</span>
                  <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                    <div className="h-full rounded-full bg-blue-600" style={{ width: `${Math.min(100, value * 12)}%` }} />
                  </div>
                  <span className="text-right font-medium text-slate-800">{value}</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-slate-50 p-3">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-900">{value}</div>
    </div>
  );
}

function toLabel(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}
