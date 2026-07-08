"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, Activity, Users, X } from "lucide-react";
import { Badge, Button, Card, CardContent, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/shared/page-header";
import { ROUTES } from "@/constants/routes";
import { useGroupAttendanceOverview } from "../hooks/use-operations";
import type { AttendanceSessionSummary } from "../api/operations.api";

export function TourGroupAttendancePage({ groupId }: { groupId: string }) {
  const { data, isLoading, error } = useGroupAttendanceOverview(groupId);
  const [missingSession, setMissingSession] = useState<AttendanceSessionSummary | null>(null);

  return (
    <div className="space-y-6">
      <PageHeader
        title={data?.group_name ? `${data.group_name} Attendance` : "Attendance"}
        description="Live coordinator activity counts and completed attendance history."
        actions={
          <Link
            href={ROUTES.dashboard.tourOperationsGroupAssignments}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Groups
          </Link>
        }
      />

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Attendance could not be loaded.
        </div>
      )}

      <Card>
        <CardContent className="p-0">
          <div className="flex items-center gap-3 border-b border-slate-200 p-5">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
              <Activity className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <h2 className="text-base font-semibold text-slate-900">Activities</h2>
              <p className="text-sm text-slate-500">Refreshes automatically every 10 seconds.</p>
            </div>
          </div>

          {isLoading ? (
            <div className="space-y-3 p-5">
              {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-24 rounded-lg" />)}
            </div>
          ) : !data || data.sessions.length === 0 ? (
            <div className="p-5">
              <p className="rounded-lg border border-dashed border-slate-300 px-3 py-8 text-center text-sm text-slate-500">
                No attendance activities started yet.
              </p>
            </div>
          ) : (
            <div className="divide-y divide-slate-100">
              {data.sessions.map((session) => (
                <div key={session.id} className="space-y-4 p-5">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-base font-semibold text-slate-900">{session.name}</h3>
                        <Badge variant={session.status === "completed" ? "success" : "secondary"}>{session.status}</Badge>
                      </div>
                      <p className="mt-1 text-sm text-slate-500">
                        {session.scanned_count}/{session.assigned_count} people counted
                      </p>
                    </div>
                    <div className="flex flex-col gap-2 md:items-end">
                      <div className="text-sm font-semibold text-slate-900">
                        {session.assigned_count === 0 ? 0 : Math.round((session.scanned_count / session.assigned_count) * 100)}%
                      </div>
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        disabled={(session.missing_passengers?.length ?? 0) === 0}
                        onClick={() => setMissingSession(session)}
                      >
                        <Users className="h-4 w-4" aria-hidden="true" />
                        Missing ({session.missing_passengers?.length ?? 0})
                      </Button>
                    </div>
                  </div>

                  <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className="h-full rounded-full bg-blue-600"
                      style={{ width: `${session.assigned_count === 0 ? 0 : Math.min(100, (session.scanned_count / session.assigned_count) * 100)}%` }}
                    />
                  </div>

                  <div className="grid gap-2 md:grid-cols-2">
                    {session.coordinators.map((coordinator) => (
                      <div key={coordinator.coordinator_id} className="rounded-lg border border-slate-200 p-3">
                        <div className="flex items-center justify-between gap-3">
                          <p className="truncate text-sm font-medium text-slate-900">{coordinator.coordinator_name}</p>
                          <Badge variant="outline">{coordinator.scanned_count}/{coordinator.assigned_count}</Badge>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {missingSession && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm">
          <div className="w-full max-w-2xl overflow-hidden rounded-xl bg-white shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4">
              <div>
                <h2 className="text-base font-semibold text-slate-950">Missing People</h2>
                <p className="mt-1 text-sm text-slate-500">
                  {missingSession.name} - {missingSession.scanned_count}/{missingSession.assigned_count} counted
                </p>
              </div>
              <button
                type="button"
                onClick={() => setMissingSession(null)}
                className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                aria-label="Close missing people list"
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>

            <div className="max-h-[65vh] overflow-y-auto p-4">
              <div className="space-y-2">
                {missingSession.missing_passengers.map((passenger) => (
                  <div key={passenger.passenger_id} className="rounded-lg border border-slate-200 p-3">
                    <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-slate-950">{passenger.client_name}</p>
                        <p className="mt-0.5 truncate text-xs text-slate-500">
                          {[passenger.client_phone, passenger.client_email].filter(Boolean).join(" | ") || "No contact"}
                        </p>
                      </div>
                      <Badge variant="outline">{passenger.coordinator_name}</Badge>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
