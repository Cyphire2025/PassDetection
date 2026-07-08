"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Camera, CheckCircle2, ClipboardList, LogIn } from "lucide-react";
import { Badge, Button, Input, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { selectIsAuthenticated, selectUser, useAuthStore } from "@/stores/auth.store";
import {
  useCreateMyAttendanceSession,
  useMyAttendanceSessions,
  useMyTourGroupPassengers,
  useMyTourGroups,
} from "@/features/operations/hooks/use-operations";
import { useEffect, useState } from "react";
import { CoordinatorFrame } from "./coordinator-mobile-shell";
import type { TourPassenger } from "@/features/operations/api/operations.api";
import { offlineSnapshotKeys, readOfflineSnapshot, writeOfflineSnapshot } from "../services/offline-snapshot";
import { mergeAttendanceSessionProgress } from "../services/attendance-session-progress";

export function CoordinatorGroupActivityPage({ groupId }: { groupId: string }) {
  const router = useRouter();
  const user = useAuthStore(selectUser);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const clearSession = useAuthStore((state) => state.clearSession);
  const isCoordinator = isAuthenticated && user?.role === "agency_coordinator";
  const { data: groups = [] } = useMyTourGroups(isCoordinator);
  const group = groups.find((item) => item.id === groupId) ?? null;
  const { data: passengers = [], isLoading: passengersLoading } = useMyTourGroupPassengers(groupId, isCoordinator);
  const [cachedPassengers] = useState<TourPassenger[]>(() =>
    readOfflineSnapshot(offlineSnapshotKeys.myPassengers(groupId), []),
  );
  const visiblePassengers = passengers.length > 0 ? passengers : cachedPassengers;
  const { data: sessions = [] } = useMyAttendanceSessions(groupId, isCoordinator);
  const visibleSessions = mergeAttendanceSessionProgress(sessions);
  const createSession = useCreateMyAttendanceSession();
  const [activityName, setActivityName] = useState("");

  useEffect(() => {
    if (passengers.length === 0) return;
    writeOfflineSnapshot(offlineSnapshotKeys.myPassengers(groupId), passengers);
  }, [groupId, passengers]);

  if (!isAuthenticated || !isCoordinator) {
    return (
      <CoordinatorFrame>
        <div className="flex flex-1 flex-col items-center justify-center px-5 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-50 text-blue-600">
            <LogIn className="h-7 w-7" aria-hidden="true" />
          </div>
          <h1 className="mt-5 text-xl font-bold text-slate-950">Coordinator login required</h1>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            Sign in with a coordinator account to use this group workflow.
          </p>
          <Button
            type="button"
            className="mt-6 h-12 w-full"
            onClick={() => {
              clearSession();
              router.push(ROUTES.auth.login as never);
            }}
          >
            Switch Account
          </Button>
        </div>
      </CoordinatorFrame>
    );
  }

  return (
    <CoordinatorFrame>
      <header className="px-4 pb-4 pt-[max(1rem,env(safe-area-inset-top))]">
        <Link href={ROUTES.coordinator as never} className="mb-4 inline-flex items-center gap-2 text-sm font-medium text-slate-600">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Groups
        </Link>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase text-blue-600">Selected Group</p>
            <h1 className="mt-1 truncate text-xl font-bold text-slate-950">{group?.name ?? "Group"}</h1>
            {group && (
              <p className="mt-1 truncate text-sm text-slate-500">
                {[group.destination, group.travel_date].filter(Boolean).join(" | ") || "No trip details"}
              </p>
            )}
          </div>
          {group?.status && <Badge variant={group.status === "active" ? "success" : "outline"}>{group.status}</Badge>}
        </div>
      </header>

      <main className="flex-1 space-y-4 px-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
        <section className="grid grid-cols-2 gap-3">
          <Metric label="People" value={visiblePassengers.length} />
          <Metric label="Activities" value={visibleSessions.length} />
        </section>

        <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 p-4">
            <h2 className="text-base font-semibold text-slate-950">Current Activity</h2>
            <p className="mt-1 text-sm text-slate-500">Name this count before scanning.</p>
          </div>
          <form
            className="space-y-3 p-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (activityName.trim().length < 2) return;
              createSession.mutate(
                { groupId, name: activityName.trim() },
                {
                  onSuccess: (session) => {
                    setActivityName("");
                    router.push(`/coordinator/groups/${groupId}/scanner?sessionId=${session.id}` as never);
                  },
                },
              );
            }}
          >
            <Input
              value={activityName}
              onChange={(event) => setActivityName(event.target.value)}
              placeholder="After lunch count"
              disabled={createSession.isPending}
              required
              minLength={2}
            />
            <Button
              type="submit"
              size="lg"
              className="h-14 w-full text-base"
              isLoading={createSession.isPending}
              disabled={activityName.trim().length < 2}
              leftIcon={<Camera className="h-5 w-5" aria-hidden="true" />}
            >
              Start Scanner
            </Button>
          </form>
        </section>

        {visibleSessions.length > 0 && (
          <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-100 p-4">
              <h2 className="text-base font-semibold text-slate-950">Recent Activities</h2>
            </div>
            <div className="space-y-2 p-3">
              {visibleSessions.slice(0, 5).map((session) => (
                <button
                  key={session.id}
                  type="button"
                  onClick={() => router.push(`/coordinator/groups/${groupId}/scanner?sessionId=${session.id}` as never)}
                  className="flex w-full items-center justify-between gap-3 rounded-lg border border-slate-200 px-3 py-2 text-left text-sm hover:bg-slate-50"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-slate-900">{session.name}</span>
                    <span className="block text-xs text-slate-500">{session.scanned_count}/{session.assigned_count} counted</span>
                  </span>
                  <ClipboardList className="h-4 w-4 text-slate-400" aria-hidden="true" />
                </button>
              ))}
            </div>
          </section>
        )}

        <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 p-4">
            <h2 className="text-base font-semibold text-slate-950">Passengers</h2>
            <p className="mt-1 text-sm text-slate-500">Passengers assigned to you for this group.</p>
          </div>
          <div className="space-y-2 p-3">
            {passengersLoading ? (
              Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-14 rounded-lg" />)
            ) : visiblePassengers.length === 0 ? (
              <p className="rounded-lg border border-dashed border-slate-300 px-3 py-6 text-center text-sm text-slate-500">
                No passengers assigned to you yet.
              </p>
            ) : (
              visiblePassengers.map((passenger) => (
                <div key={passenger.id} className="rounded-lg border border-slate-200 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-slate-950">{passenger.client_name}</p>
                      <p className="mt-0.5 truncate text-xs text-slate-500">
                        {[passenger.client_phone, passenger.client_email].filter(Boolean).join(" | ") || "No contact"}
                      </p>
                    </div>
                    <CheckCircle2 className="h-5 w-5 shrink-0 text-slate-300" aria-hidden="true" />
                  </div>
                </div>
              ))
            )}
          </div>
        </section>
      </main>
    </CoordinatorFrame>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm">
      <p className="text-[11px] font-semibold uppercase text-slate-500">{label}</p>
      <p className="mt-1 text-xl font-bold text-slate-950">{value}</p>
    </div>
  );
}
