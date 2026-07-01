/**
 * Dashboard Overview — Light Theme
 */

"use client";

import Link from "next/link";
import { FileText, Link2, CheckCircle, AlertCircle, Eye } from "lucide-react";
import { Card, CardContent, Skeleton, Badge, Button } from "@/components/ui";
import { PageHeader } from "@/components/shared";
import { useDashboardStats } from "../hooks/use-dashboard-stats";
import { formatDate } from "@/lib/utils/format";
import { PASSPORT_STATUS_LABELS, PASSPORT_STATUS_COLORS } from "@/constants";
import { ROUTES } from "@/constants/routes";

interface MetricCardProps {
  label: string;
  value: number | string;
  icon: React.ComponentType<{ className?: string }>;
  iconBg: string;
  iconColor: string;
  isLoading?: boolean;
}

function MetricCard({ label, value, icon: Icon, iconBg, iconColor, isLoading }: MetricCardProps) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
            {isLoading ? (
              <Skeleton className="mt-2 h-7 w-16" />
            ) : (
              <p className="mt-1.5 text-2xl font-bold text-slate-900">{value}</p>
            )}
          </div>
          <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${iconBg}`}>
            <Icon className={`h-5 w-5 ${iconColor}`} aria-hidden="true" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function DashboardOverview() {
  const { data, isLoading, error } = useDashboardStats();

  const metrics: MetricCardProps[] = [
    {
      label: "Total Passports",
      value: data?.total_passports ?? 0,
      icon: FileText,
      iconBg: "bg-blue-50",
      iconColor: "text-blue-600",
      isLoading,
    },
    {
      label: "Pending Review",
      value: data?.pending_review ?? 0,
      icon: AlertCircle,
      iconBg: "bg-amber-50",
      iconColor: "text-amber-600",
      isLoading,
    },
    {
      label: "Confirmed",
      value: data?.confirmed ?? 0,
      icon: CheckCircle,
      iconBg: "bg-green-50",
      iconColor: "text-green-600",
      isLoading,
    },
    {
      label: "Active Links",
      value: data?.active_links ?? 0,
      icon: Link2,
      iconBg: "bg-purple-50",
      iconColor: "text-purple-600",
      isLoading,
    },
  ];

  return (
    <div className="flex flex-col gap-7">
      <PageHeader
        title="Dashboard"
        description="Overview of your passport processing activity"
      />

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-600">
          Failed to load dashboard statistics. Please ensure backend services are running.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map((m) => (
          <MetricCard key={m.label} {...m} />
        ))}
      </div>

      {/* Recent Submissions */}
      <Card>
        <CardContent className="pt-6">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-800">Recent Activity</h3>
            <Link href="/passports" className="text-xs font-semibold text-blue-600 hover:text-blue-700">
              View all
            </Link>
          </div>

          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full rounded-lg" />
              ))}
            </div>
          ) : !data?.recent_submissions || data.recent_submissions.length === 0 ? (
            <div className="py-12 text-center">
              <p className="text-sm text-slate-400">No recent submissions found.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm" role="table">
                <thead>
                  <tr className="border-b border-slate-100 text-xs font-medium uppercase tracking-wider text-slate-400">
                    <th className="pb-3 pr-4">Client</th>
                    <th className="pb-3 pr-4">Status</th>
                    <th className="pb-3 pr-4">Submitted At</th>
                    <th className="pb-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.recent_submissions.map((sub) => (
                    <tr key={sub.id} className="group hover:bg-slate-50/50">
                      <td className="py-3.5 pr-4">
                        <div className="font-medium text-slate-800">{sub.client_name}</div>
                        <div className="text-xs text-slate-400">{sub.client_email}</div>
                      </td>
                      <td className="py-3.5 pr-4">
                        <Badge variant={PASSPORT_STATUS_COLORS[sub.status] || "default"}>
                          {PASSPORT_STATUS_LABELS[sub.status] || sub.status}
                        </Badge>
                      </td>
                      <td className="py-3.5 pr-4 text-slate-500">
                        {formatDate(sub.created_at)}
                      </td>
                      <td className="py-3.5 text-right">
                        <Link href={ROUTES.dashboard.passportDetail(sub.id) as never}>
                          <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                            <Eye className="h-4 w-4 text-slate-400 group-hover:text-slate-600" />
                            <span className="sr-only">View</span>
                          </Button>
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
