"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, ArrowLeft, Camera, CheckCircle2, ClipboardList, LogIn, Hotel } from "lucide-react";
import { Badge, Button, Input, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { selectIsAuthenticated, selectUser, useAuthStore } from "@/stores/auth.store";
import {
  useCreateMyAttendanceSession,
  useMyAttendanceSessionDetails,
  useMyAttendanceSessions,
  useMyTourGroupPassengers,
  useMyTourGroups,
} from "@/features/operations/hooks/use-operations";
import { useEffect, useState } from "react";
import { CoordinatorFrame } from "./coordinator-mobile-shell";
import type { AttendancePassengerStatus, AttendanceSession, TourPassenger } from "@/features/operations/api/operations.api";
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
  const [cachedSessions] = useState<AttendanceSession[]>(() =>
    readOfflineSnapshot(offlineSnapshotKeys.mySessions(groupId), []),
  );
  const visibleSessions = mergeAttendanceSessionProgress(sessions.length > 0 ? sessions : cachedSessions);
  const createSession = useCreateMyAttendanceSession();
  const [activityName, setActivityName] = useState("");
  const [detailsSessionId, setDetailsSessionId] = useState<string | null>(null);
  const { data: sessionDetails, isLoading: detailsLoading } = useMyAttendanceSessionDetails(
    detailsSessionId,
    isCoordinator && Boolean(detailsSessionId),
  );

  useEffect(() => {
    if (passengers.length === 0) return;
    writeOfflineSnapshot(offlineSnapshotKeys.myPassengers(groupId), passengers);
  }, [groupId, passengers]);

  useEffect(() => {
    if (sessions.length === 0) return;
    writeOfflineSnapshot(offlineSnapshotKeys.mySessions(groupId), sessions);
  }, [groupId, sessions]);

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
        <Button type="button" variant="secondary" className="h-14 w-full text-base" leftIcon={<Hotel className="h-5 w-5" />} onClick={() => router.push(`/coordinator/groups/${groupId}/hotel-checkin` as never)}>Hotel Check-in</Button>

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
                <div
                  key={session.id}
                  className="rounded-lg border border-slate-200 px-3 py-3 text-sm"
                >
                  <button
                    type="button"
                    onClick={() => {
                      if (session.status === "completed") {
                        setDetailsSessionId((current) => (current === session.id ? null : session.id));
                        return;
                      }
                      router.push(`/coordinator/groups/${groupId}/scanner?sessionId=${session.id}` as never);
                    }}
                    className="flex w-full items-center justify-between gap-3 text-left hover:text-blue-700"
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-slate-900">{session.name}</span>
                      <span className="block text-xs text-slate-500">{session.scanned_count}/{session.assigned_count} counted</span>
                    </span>
                    <span className="flex items-center gap-2">
                      <Badge variant={session.status === "completed" ? "success" : "outline"}>{session.status}</Badge>
                      <ClipboardList className="h-4 w-4 text-slate-400" aria-hidden="true" />
                    </span>
                  </button>
                  {session.status === "completed" && (
                    <div className="mt-3 grid grid-cols-2 gap-2">
                      <Button
                        type="button"
                        variant="secondary"
                        className="h-10"
                        leftIcon={<Camera className="h-4 w-4" aria-hidden="true" />}
                        onClick={() => router.push(`/coordinator/groups/${groupId}/scanner?sessionId=${session.id}` as never)}
                      >
                        Scan
                      </Button>
                      <Button
                        type="button"
                        variant={detailsSessionId === session.id ? "primary" : "outline"}
                        className="h-10"
                        leftIcon={<ClipboardList className="h-4 w-4" aria-hidden="true" />}
                        onClick={() => setDetailsSessionId((current) => (current === session.id ? null : session.id))}
                      >
                        Details
                      </Button>
                    </div>
                  )}
                  {detailsSessionId === session.id && (
                    <AttendanceDetailsCard
                      groupId={groupId}
                      sessionId={session.id}
                      details={sessionDetails}
                      isLoading={detailsLoading}
                    />
                  )}
                </div>
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

function AttendanceDetailsCard({
  groupId,
  sessionId,
  details,
  isLoading,
}: {
  groupId: string;
  sessionId: string;
  details?: {
    missing_passengers: AttendancePassengerStatus[];
    scanned_passengers: AttendancePassengerStatus[];
    scanned_count: number;
    assigned_count: number;
  };
  isLoading: boolean;
}) {
  return (
    <div className="mt-3 space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
      <Link
        href={`/coordinator/groups/${groupId}/scanner?sessionId=${sessionId}` as never}
        className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 text-sm font-semibold text-white shadow-sm hover:bg-blue-700"
      >
        <Camera className="h-4 w-4" aria-hidden="true" />
        Scan again
      </Link>
      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-16 rounded-lg" />
          <Skeleton className="h-16 rounded-lg" />
        </div>
      ) : !details ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700">
          Details are not available offline yet. Connect once to refresh this activity.
        </p>
      ) : (
        <>
          <section className="rounded-lg border border-red-200 bg-red-50 p-3">
            <div className="flex items-center justify-between gap-3">
              <h3 className="inline-flex items-center gap-2 text-sm font-bold text-red-800">
                <AlertTriangle className="h-4 w-4" aria-hidden="true" />
                Missing people
              </h3>
              <span className="text-xs font-semibold text-red-700">{details.missing_passengers.length}</span>
            </div>
            <PassengerList
              groupId={groupId}
              passengers={details.missing_passengers}
              emptyText="No one is missing for this activity."
            />
          </section>
          <section className="rounded-lg border border-emerald-200 bg-white p-3">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-bold text-slate-900">Scanned people</h3>
              <span className="text-xs font-semibold text-slate-500">
                {details.scanned_count}/{details.assigned_count}
              </span>
            </div>
            <PassengerList groupId={groupId} passengers={details.scanned_passengers} emptyText="No passengers scanned yet." />
          </section>
        </>
      )}
    </div>
  );
}

function PassengerList({
  groupId,
  passengers,
  emptyText,
}: {
  groupId: string;
  passengers: AttendancePassengerStatus[];
  emptyText: string;
}) {
  if (passengers.length === 0) {
    return <p className="mt-2 rounded-md border border-dashed border-current/20 p-3 text-xs text-slate-500">{emptyText}</p>;
  }
  return (
    <div className="mt-2 space-y-2">
      {passengers.map((passenger) => (
        <Link
          key={passenger.passenger_id}
          href={`/coordinator/groups/${groupId}/passengers/${passenger.passenger_id}` as never}
          className="group block rounded-lg border border-white/60 bg-white/80 p-2 transition hover:border-blue-200 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-slate-950">{passenger.client_name}</p>
              <p className="mt-0.5 truncate text-xs text-slate-500">
            {[passenger.client_phone, passenger.client_email, passenger.departure_city].filter(Boolean).join(" | ") ||
              "No extra details"}
              </p>
            </div>
            <span className="shrink-0 rounded-full bg-white px-2 py-1 text-[11px] font-semibold text-blue-700 opacity-100 shadow-sm sm:opacity-0 sm:transition sm:group-hover:opacity-100 sm:group-focus:opacity-100">
              View more details
            </span>
          </div>
        </Link>
      ))}
    </div>
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
