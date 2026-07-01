"use client";

import Link from "next/link";
import { Eye, FileText, FolderOpen } from "lucide-react";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Badge, Button, Card, CardContent, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { formatDateTime } from "@/lib/utils/format";
import type { PassportGroupSummary } from "@/types/passport.types";
import { usePassportGroups } from "../hooks/use-passports";

export function PassportList() {
  const { data, isLoading, error } = usePassportGroups();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Passport Groups"
        description="Open a client group to review the passport submissions uploaded inside it."
      />

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Failed to load passport submissions. Check that the backend is running and reachable.
        </div>
      )}

      {isLoading ? (
        <div className="grid gap-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-28 w-full rounded-2xl" />
          ))}
        </div>
      ) : !data || data.length === 0 ? (
        <EmptyState
          icon={<FileText className="h-5 w-5" />}
          title="No passport groups with uploads yet"
          description="Groups will appear here after clients upload at least one passport."
        />
      ) : (
        <>
          <div className="grid gap-4 lg:hidden">
            {data.map((group) => (
              <PassportGroupMobileCard key={group.group_id} group={group} />
            ))}
          </div>

          <Card className="hidden lg:block">
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                      <th className="px-6 py-4">Group</th>
                      <th className="px-6 py-4">Status</th>
                      <th className="px-6 py-4">Passports</th>
                      <th className="px-6 py-4">Needs Review</th>
                      <th className="px-6 py-4">Latest Upload</th>
                      <th className="px-6 py-4 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.map((group) => (
                      <tr key={group.group_id} className="hover:bg-slate-50/60">
                        <td className="px-6 py-4">
                          <div className="font-semibold text-slate-900">{group.group_name}</div>
                          <div className="mt-1 text-xs text-slate-500">{group.confirmed_count} confirmed, {group.failed_count} failed</div>
                        </td>
                        <td className="px-6 py-4">
                          <GroupStatusBadge status={group.group_status} />
                        </td>
                        <td className="px-6 py-4 text-slate-700">{group.total_passports}</td>
                        <td className="px-6 py-4">
                          <span className="font-medium text-slate-800">{group.pending_review_count}</span>
                        </td>
                        <td className="px-6 py-4 text-slate-500">{formatDateTime(group.latest_submission_at)}</td>
                        <td className="px-6 py-4 text-right">
                          <Link href={ROUTES.dashboard.passportGroup(group.group_id) as never}>
                            <Button variant="outline" size="sm" className="gap-2">
                              <Eye className="h-4 w-4" />
                              Open Group
                            </Button>
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function PassportGroupMobileCard({ group }: { group: PassportGroupSummary }) {
  return (
    <Card className="rounded-2xl">
      <CardContent className="space-y-4 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-slate-900">{group.group_name}</h3>
            <p className="mt-1 text-xs text-slate-500">{formatDateTime(group.latest_submission_at)}</p>
          </div>
          <GroupStatusBadge status={group.group_status} />
        </div>

        <div className="grid grid-cols-2 gap-3 text-sm">
          <InfoPair label="Passports" value={String(group.total_passports)} />
          <InfoPair label="Needs Review" value={String(group.pending_review_count)} />
          <InfoPair label="Confirmed" value={String(group.confirmed_count)} />
          <InfoPair label="Failed" value={String(group.failed_count)} />
        </div>

        <Link href={ROUTES.dashboard.passportGroup(group.group_id) as never} className="block">
          <Button variant="outline" className="w-full gap-2">
            <FolderOpen className="h-4 w-4" />
            Open Group
          </Button>
        </Link>
      </CardContent>
    </Card>
  );
}

function InfoPair({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 font-medium text-slate-800">{value}</div>
    </div>
  );
}

function GroupStatusBadge({ status }: { status: string }) {
  const variant = status === "active" ? "secondary" : status === "closed" ? "outline" : "default";
  return (
    <Badge variant={variant} dot>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </Badge>
  );
}
