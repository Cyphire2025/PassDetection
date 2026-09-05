"use client";

import Link from "next/link";
import { Archive, Database, Eye, FileText, RotateCcw } from "lucide-react";
import { EmptyState } from "@/components/shared/empty-state";
import { WorkspacePageHeader } from "@/components/shared/workspace-ui";
import { Badge, Button, Card, CardContent, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { useRestoreUploadLink, useUploadLinks } from "@/features/passports/hooks/use-upload-links";

export default function OldDataPage() {
  const { data: deletedGroups = [], isLoading, error } = useUploadLinks("deleted");
  const restoreGroup = useRestoreUploadLink();
  const retainedGroups = deletedGroups.filter((group) => group.deletion_retained_records);

  return (
    <div className="flex flex-col gap-6">
      <WorkspacePageHeader
        icon={Archive}
        title="Old Data"
        description="Deleted groups whose passport records were retained for Super Admin access."
      />

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Failed to load old group data.
        </div>
      )}

      {isLoading ? (
        <div className="grid gap-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-24 w-full rounded-2xl" />
          ))}
        </div>
      ) : retainedGroups.length === 0 ? (
        <EmptyState
          icon={<Database className="h-5 w-5" />}
          title="No old data saved"
          description="Deleted groups will appear here only when Super Admin chooses to keep their passport records."
        />
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                  <tr>
                    <th className="px-6 py-4">Group</th>
                    <th className="px-6 py-4">Saved Records</th>
                    <th className="px-6 py-4">Deleted</th>
                    <th className="px-6 py-4">Status</th>
                    <th className="px-6 py-4 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {retainedGroups.map((group) => (
                    <tr key={group.id} className="hover:bg-slate-50/60">
                      <td className="px-6 py-4">
                        <div className="font-semibold text-slate-900">{group.name}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          {[group.destination, group.travel_date].filter(Boolean).join(" | ") || "No trip details"}
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2 text-slate-800">
                          <FileText className="h-4 w-4 text-slate-400" />
                          {group.deleted_passport_count} passports
                        </div>
                      </td>
                      <td className="px-6 py-4 text-slate-500">
                        {group.deleted_at ? new Date(group.deleted_at).toLocaleString() : "-"}
                      </td>
                      <td className="px-6 py-4">
                        <Badge variant="default">
                          <Archive className="h-3.5 w-3.5" />
                          Saved
                        </Badge>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex justify-end gap-2">
                          <Link href={`${ROUTES.dashboard.passportGroup(group.id)}?old_data=1` as never}>
                            <Button variant="outline" size="sm" className="gap-2">
                              <Eye className="h-4 w-4" />
                              Open Data
                            </Button>
                          </Link>
                          <Button
                            variant="secondary"
                            size="sm"
                            className="gap-2"
                            disabled={restoreGroup.isPending}
                            onClick={() => restoreGroup.mutate(group.id)}
                          >
                            <RotateCcw className="h-4 w-4" />
                            Restore
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
