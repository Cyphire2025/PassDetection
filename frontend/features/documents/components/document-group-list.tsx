"use client";

import Link from "next/link";
import { ArrowLeft, FileStack, FolderOpen } from "lucide-react";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Badge, Button, Card, CardContent, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { useDocumentGroups } from "../hooks/use-document-distribution";

export function DocumentGroupList() {
  const { data: groups = [], isLoading, error } = useDocumentGroups();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Document Distribution"
        description="Upload visas, tickets, and other travel documents, then match them to passengers before sending."
        actions={(
          <Link href={ROUTES.dashboard.documents as never}>
            <Button type="button" variant="outline">
              <ArrowLeft className="h-4 w-4" />
              Back
            </Button>
          </Link>
        )}
      />

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Failed to load groups for document distribution.
        </div>
      )}

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-36 rounded-xl" />
          ))}
        </div>
      ) : groups.length === 0 ? (
        <EmptyState
          icon={<FileStack className="h-5 w-5" />}
          title="No active groups"
          description="Create a group and add passengers before distributing documents."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {groups.map((group) => (
            <Card key={group.group_id} className="transition hover:border-blue-200 hover:shadow-md">
              <CardContent className="space-y-4 p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-base font-semibold text-slate-900">{group.group_name}</h2>
                    <p className="mt-1 text-sm text-slate-500">{group.destination || "Destination not set"}</p>
                  </div>
                  <Badge variant={group.group_status === "active" ? "secondary" : "outline"} dot>
                    {group.group_status}
                  </Badge>
                </div>

                <div className="grid grid-cols-2 gap-3 text-sm">
                  <InfoPair label="Passengers" value={String(group.total_passengers)} />
                  <InfoPair label="Travel Date" value={group.travel_date || "Not set"} />
                </div>

                <Link href={ROUTES.dashboard.documentGroup(group.group_id) as never} className="block">
                  <Button variant="outline" className="w-full">
                    <FolderOpen className="h-4 w-4" />
                    Open Documents
                  </Button>
                </Link>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
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
