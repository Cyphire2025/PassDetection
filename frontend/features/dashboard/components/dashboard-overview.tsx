/**
 * Today at a glance.
 */

"use client";

import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import {
WorkspaceErrorNotice,
WorkspacePageHeader,
WorkspaceSummaryItem,
WorkspaceSummaryStrip,
} from "@/components/shared/workspace-ui";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { PASSPORT_STATUS_COLORS,PASSPORT_STATUS_LABELS } from "@/constants";
import { ROUTES } from "@/constants/routes";
import { formatDate } from "@/lib/utils/format";
import { selectUserRole,useAuthStore } from "@/stores/auth.store";
import {
Activity,
AlertCircle,
ArrowRight,
CalendarCheck,
CheckCircle2,
Eye,
FileText,
Link2,
} from "lucide-react";
import Link from "next/link";
import { useDashboardStats } from "../hooks/use-dashboard-stats";

export function DashboardOverview() {
  const role = useAuthStore(selectUserRole);
  const isCoordinator = role === "agency_coordinator";
  const { data, isLoading, error } = useDashboardStats({ enabled: !isCoordinator });

  if (isCoordinator) {
    return (
      <div className="flex min-w-0 flex-col gap-5">
        <WorkspacePageHeader
          title="Dashboard"
          description="Open an assigned tour group to record attendance."
          icon={CalendarCheck}
          accent="lime"
          actions={(
            <Link
              href={ROUTES.coordinator as never}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-white px-4 text-sm font-semibold text-[#123f73] shadow-sm transition hover:bg-sky-50 active:bg-sky-100"
            >
              Open My Tour
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
          )}
        />

        <section
          className="grid overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm md:grid-cols-[minmax(0,1fr)_auto]"
          aria-labelledby="coordinator-next-step"
        >
          <div className="p-5 sm:p-6">
            <h2 id="coordinator-next-step" className="mt-1 text-lg font-semibold text-slate-950">
              Continue from your assigned group
            </h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
              Choose a group and activity to scan passenger QR codes or review attendance.
            </p>
          </div>
          <div className="flex items-center border-t border-slate-100 bg-slate-50/70 p-5 md:border-l md:border-t-0">
            <Link
              href={ROUTES.coordinator as never}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 md:w-auto"
            >
              My Tour
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <WorkspacePageHeader
        title="Dashboard"
        description="Your latest passport activity and the records that need attention."
        icon={Activity}
        accent="sky"
        actions={(
          <IntentPrefetchLink
            href={ROUTES.dashboard.passports}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-white px-4 text-sm font-semibold text-[#123f73] shadow-sm transition hover:bg-sky-50 active:bg-sky-100"
          >
            Open All Groups
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </IntentPrefetchLink>
        )}
      />

      {error && (
        <WorkspaceErrorNotice>
          Dashboard statistics could not be refreshed. Please try again.
        </WorkspaceErrorNotice>
      )}

      <WorkspaceSummaryStrip label="Passport operations summary">
        {isLoading ? (
          Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-[72px] rounded-none" />
          ))
        ) : (
          <>
            <WorkspaceSummaryItem
              label="Passport records"
              value={(data?.total_passports ?? 0).toLocaleString()}
              icon={FileText}
            />
            <WorkspaceSummaryItem
              label="Needs review"
              value={(data?.pending_review ?? 0).toLocaleString()}
              icon={AlertCircle}
              tone={(data?.pending_review ?? 0) > 0 ? "attention" : "success"}
            />
            <WorkspaceSummaryItem
              label="Confirmed"
              value={(data?.confirmed ?? 0).toLocaleString()}
              icon={CheckCircle2}
              tone="success"
            />
            <WorkspaceSummaryItem
              label="Active links"
              value={(data?.active_links ?? 0).toLocaleString()}
              helper="collecting details"
              icon={Link2}
              tone="info"
            />
          </>
        )}
      </WorkspaceSummaryStrip>

      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        aria-labelledby="recent-activity-heading"
      >
        <div className="flex flex-col gap-3 border-b border-slate-200 bg-slate-50/70 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <div>
            <h2 id="recent-activity-heading" className="mt-0.5 font-semibold text-slate-950">
              Recent passport activity
            </h2>
          </div>
          <IntentPrefetchLink
            href={ROUTES.dashboard.passports}
            className="inline-flex items-center gap-1.5 text-sm font-semibold text-blue-700 hover:text-blue-800"
          >
            View all groups
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </IntentPrefetchLink>
        </div>

        {isLoading ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 4 }).map((_, index) => (
              <Skeleton key={index} className="h-14 w-full rounded-lg" />
            ))}
          </div>
        ) : !data?.recent_submissions || data.recent_submissions.length === 0 ? (
          <div className="px-5 py-12 text-center">
            <FileText className="mx-auto h-6 w-6 text-slate-400" aria-hidden="true" />
            <h3 className="mt-3 text-sm font-semibold text-slate-900">No recent passport intake</h3>
            <p className="mx-auto mt-1 max-w-md text-sm leading-6 text-slate-500">
              New client submissions will appear here as soon as a group link receives verified details.
            </p>
          </div>
        ) : (
          <>
            <div className="divide-y divide-slate-100 md:hidden">
              {data.recent_submissions.map((submission) => (
                <article key={submission.id} className="px-4 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="font-semibold text-slate-950">
                        {submission.client_name}
                      </h3>
                      <p className="mt-1 break-all text-xs text-slate-500">
                        {submission.client_email}
                      </p>
                    </div>
                    <Badge variant={PASSPORT_STATUS_COLORS[submission.status] || "default"}>
                      {PASSPORT_STATUS_LABELS[submission.status] || submission.status}
                    </Badge>
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-3 border-t border-slate-100 pt-3">
                    <p className="text-xs text-slate-500">
                      Submitted {formatDate(submission.created_at)}
                    </p>
                    <IntentPrefetchLink
                      href={ROUTES.dashboard.passportDetail(submission.id)}
                      className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 text-xs font-semibold text-slate-700 transition hover:border-blue-300 hover:bg-blue-50 hover:text-blue-800"
                      aria-label={`Review ${submission.client_name}`}
                    >
                      <Eye className="h-4 w-4" aria-hidden="true" />
                      Review
                    </IntentPrefetchLink>
                  </div>
                </article>
              ))}
            </div>

            <div className="hidden overflow-x-auto md:block">
            <table className="w-full min-w-[680px] text-left text-sm">
              <caption className="sr-only">Recent passport activity</caption>
              <thead>
                <tr className="border-b border-slate-100 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                  <th scope="col" className="px-5 py-3">Passenger</th>
                  <th scope="col" className="px-5 py-3">Workflow status</th>
                  <th scope="col" className="px-5 py-3">Submitted</th>
                  <th scope="col" className="px-5 py-3 text-right">Review</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.recent_submissions.map((submission) => (
                  <tr key={submission.id} className="group transition-colors hover:bg-slate-50/70">
                    <td className="px-5 py-3.5">
                      <div className="font-medium text-slate-900">{submission.client_name}</div>
                      <div className="mt-0.5 text-xs text-slate-500">{submission.client_email}</div>
                    </td>
                    <td className="px-5 py-3.5">
                      <Badge variant={PASSPORT_STATUS_COLORS[submission.status] || "default"}>
                        {PASSPORT_STATUS_LABELS[submission.status] || submission.status}
                      </Badge>
                    </td>
                    <td className="px-5 py-3.5 text-slate-600">
                      {formatDate(submission.created_at)}
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      <IntentPrefetchLink
                        href={ROUTES.dashboard.passportDetail(submission.id)}
                        className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 transition hover:bg-blue-50 hover:text-blue-700"
                        aria-label={`Review ${submission.client_name}`}
                      >
                        <Eye className="h-4 w-4" aria-hidden="true" />
                      </IntentPrefetchLink>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
