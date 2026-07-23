"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  Camera,
  CheckCircle2,
  ClipboardList,
  CloudOff,
  Hotel,
  LogIn,
  RefreshCw,
} from "lucide-react";
import { Badge, Button, Input, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import {
  selectHasHydrated,
  selectIsAuthenticated,
  selectUser,
  useAuthStore,
} from "@/stores/auth.store";
import {
  useCreateMyAttendanceSession,
  useMyAttendanceSessionDetails,
  useMyAttendanceSessions,
  useMyTourGroupPassengers,
  useMyTourGroups,
} from "@/features/operations/hooks/use-operations";
import { memo, useEffect, useMemo, useState } from "react";
import { CoordinatorFrame, CoordinatorHydrationState } from "./coordinator-mobile-shell";
import type {
  AttendancePassengerStatus,
  AttendanceSession,
  TourGroup,
  TourPassenger,
} from "@/features/operations/api/operations.api";
import { offlineSnapshotKeys, readOfflineSnapshot, writeOfflineSnapshot } from "../services/offline-snapshot";
import {
  mergeAttendanceSessionProgress,
  reconcileAttendanceSessionProgress,
} from "../services/attendance-session-progress";
import { selectVisibleAttendanceSessions } from "../services/attendance-sync-policy";
import { useNetworkStatus } from "../hooks/use-network-status";

const PASSENGER_PAGE_SIZE = 50;
const EMPTY_GROUPS: TourGroup[] = [];
const EMPTY_PASSENGERS: TourPassenger[] = [];
const EMPTY_SESSIONS: AttendanceSession[] = [];

export function CoordinatorGroupActivityPage({ groupId }: { groupId: string }) {
  const router = useRouter();
  const user = useAuthStore(selectUser);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const hasHydrated = useAuthStore(selectHasHydrated);
  const clearSession = useAuthStore((state) => state.clearSession);
  const isOnline = useNetworkStatus();
  const isCoordinator = isAuthenticated && user?.role === "agency_coordinator";
  const userId = user?.id;
  const groupsQuery = useMyTourGroups(hasHydrated && isCoordinator);
  const groups = groupsQuery.data ?? EMPTY_GROUPS;
  const cachedGroups = useMemo<TourGroup[]>(
    () => userId ? readOfflineSnapshot(offlineSnapshotKeys.myGroups, []) : [],
    [userId],
  );
  const visibleGroups = groupsQuery.isSuccess ? groups : cachedGroups;
  const group = visibleGroups.find((item) => item.id === groupId) ?? null;
  const passengersQuery = useMyTourGroupPassengers(groupId, hasHydrated && isCoordinator);
  const passengers = passengersQuery.data ?? EMPTY_PASSENGERS;
  const cachedPassengers = useMemo<TourPassenger[]>(
    () => userId ? readOfflineSnapshot(offlineSnapshotKeys.myPassengers(groupId), []) : [],
    [groupId, userId],
  );
  const visiblePassengers = passengersQuery.isSuccess ? passengers : cachedPassengers;
  const sessionsQuery = useMyAttendanceSessions(groupId, hasHydrated && isCoordinator);
  const sessions = sessionsQuery.data ?? EMPTY_SESSIONS;
  const cachedSessions = useMemo<AttendanceSession[]>(
    () => userId ? readOfflineSnapshot(offlineSnapshotKeys.mySessions(groupId), []) : [],
    [groupId, userId],
  );
  const visibleSessions = useMemo(
    () => selectVisibleAttendanceSessions(
      sessionsQuery.isSuccess,
      sessions,
      cachedSessions,
      mergeAttendanceSessionProgress,
    ),
    [cachedSessions, sessions, sessionsQuery.isSuccess],
  );
  const [detailsSessionId, setDetailsSessionId] = useState<string | null>(null);
  const detailsQuery = useMyAttendanceSessionDetails(
    detailsSessionId,
    hasHydrated && isCoordinator && Boolean(detailsSessionId),
  );

  useEffect(() => {
    if (!passengersQuery.isSuccess) return;
    writeOfflineSnapshot(offlineSnapshotKeys.myPassengers(groupId), passengers);
  }, [groupId, passengers, passengersQuery.isSuccess]);

  useEffect(() => {
    if (!sessionsQuery.isSuccess) return;
    reconcileAttendanceSessionProgress(sessions);
    writeOfflineSnapshot(offlineSnapshotKeys.mySessions(groupId), sessions);
  }, [groupId, sessions, sessionsQuery.isSuccess]);

  if (!hasHydrated) {
    return <CoordinatorHydrationState label="Loading group activity" />;
  }

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
              if (isAuthenticated) {
                void clearSession();
                return;
              }
              router.push(ROUTES.auth.coordinatorLogin(`/coordinator/groups/${groupId}`) as never);
            }}
          >
            {isAuthenticated ? "Switch Account" : "Login"}
          </Button>
        </div>
      </CoordinatorFrame>
    );
  }

  return (
    <CoordinatorFrame>
      <header className="px-4 pb-4 pt-[max(1rem,env(safe-area-inset-top))]">
        <Link href={ROUTES.coordinator as never} className="mb-3 inline-flex min-h-11 items-center gap-2 rounded-lg pr-3 text-sm font-medium text-slate-600">
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
        {!isOnline && (
          <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            <CloudOff className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <p>Offline mode: saved groups and passengers remain visible. Reconnect before starting or completing an activity.</p>
          </div>
        )}
        {(groupsQuery.error || passengersQuery.error || sessionsQuery.error) && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            <p>
              {visiblePassengers.length > 0 || visibleSessions.length > 0
                ? "Some live data is unavailable. Saved information is shown where possible."
                : "Group data could not be refreshed."}
            </p>
            <Button
              type="button"
              variant="secondary"
              className="mt-3 h-11 w-full"
              leftIcon={<RefreshCw className="h-4 w-4" aria-hidden="true" />}
              isLoading={groupsQuery.isFetching || passengersQuery.isFetching || sessionsQuery.isFetching}
              onClick={() => {
                void Promise.all([
                  groupsQuery.refetch(),
                  passengersQuery.refetch(),
                  sessionsQuery.refetch(),
                ]);
              }}
            >
              Refresh group
            </Button>
          </div>
        )}
        <section className="grid grid-cols-2 gap-3">
          <Metric label="People" value={visiblePassengers.length} />
          <Metric label="Activities" value={visibleSessions.length} />
        </section>
        <Button
          type="button"
          variant="secondary"
          className="h-14 w-full text-base"
          leftIcon={<Hotel className="h-5 w-5" aria-hidden="true" />}
          onClick={() => router.push(`/coordinator/groups/${groupId}/hotel-checkin` as never)}
        >
          Hotel Check-in
        </Button>

        <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 p-4">
            <h2 className="text-base font-semibold text-slate-950">Current Activity</h2>
            <p className="mt-1 text-sm text-slate-500">Name this count before scanning.</p>
          </div>
          <ActivityStarter groupId={groupId} isOnline={isOnline} />
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
                    className="flex min-h-11 w-full items-center justify-between gap-3 text-left hover:text-blue-700"
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
                    <div className="mt-3">
                      <Button
                        type="button"
                        variant={detailsSessionId === session.id ? "primary" : "outline"}
                        className="h-11 w-full"
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
                      details={detailsQuery.data}
                      isLoading={detailsQuery.isLoading}
                      isError={detailsQuery.isError}
                      onRetry={() => void detailsQuery.refetch()}
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
          <PassengerRoster
            key={groupId}
            passengers={visiblePassengers}
            isLoading={passengersQuery.isLoading && visiblePassengers.length === 0}
          />
        </section>
      </main>
    </CoordinatorFrame>
  );
}

function ActivityStarter({ groupId, isOnline }: { groupId: string; isOnline: boolean }) {
  const router = useRouter();
  const createSession = useCreateMyAttendanceSession();
  const [activityName, setActivityName] = useState("");
  const normalizedName = activityName.trim();

  return (
    <form
      className="space-y-3 p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!isOnline || normalizedName.length < 2 || createSession.isPending) return;
        createSession.mutate(
          { groupId, name: normalizedName },
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
        id="coordinator-activity-name"
        label="Activity name"
        value={activityName}
        onChange={(event) => setActivityName(event.target.value)}
        placeholder="After lunch count"
        disabled={createSession.isPending || !isOnline}
        required
        minLength={2}
        maxLength={120}
        autoComplete="off"
        className="h-12 text-base"
      />
      {!isOnline && <p className="text-xs text-amber-700">Reconnect to create a new activity.</p>}
      {createSession.isError && (
        <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          The activity could not be created. Check the connection and try again.
        </p>
      )}
      <Button
        type="submit"
        size="lg"
        className="h-14 w-full text-base"
        isLoading={createSession.isPending}
        disabled={!isOnline || normalizedName.length < 2}
        leftIcon={<Camera className="h-5 w-5" aria-hidden="true" />}
      >
        Start Scanner
      </Button>
    </form>
  );
}

const PassengerRoster = memo(function PassengerRoster({
  passengers,
  isLoading,
}: {
  passengers: TourPassenger[];
  isLoading: boolean;
}) {
  const [visibleCount, setVisibleCount] = useState(PASSENGER_PAGE_SIZE);

  if (isLoading) {
    return (
      <div className="space-y-2 p-3">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-14 rounded-lg" />
        ))}
      </div>
    );
  }

  if (passengers.length === 0) {
    return (
      <div className="p-3">
        <p className="rounded-lg border border-dashed border-slate-300 px-3 py-6 text-center text-sm text-slate-500">
          No passengers assigned to you yet.
        </p>
      </div>
    );
  }

  const visiblePassengers = passengers.slice(0, visibleCount);
  const remainingCount = passengers.length - visiblePassengers.length;

  return (
    <div className="space-y-2 p-3">
      {visiblePassengers.map((passenger) => (
        <div
          key={passenger.id}
          className="min-h-14 rounded-lg border border-slate-200 p-3 [contain-intrinsic-size:auto_3.5rem] [content-visibility:auto]"
        >
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
      ))}
      {remainingCount > 0 && (
        <Button
          type="button"
          variant="secondary"
          className="h-11 w-full"
          onClick={() => setVisibleCount((current) => Math.min(current + PASSENGER_PAGE_SIZE, passengers.length))}
        >
          Show {Math.min(PASSENGER_PAGE_SIZE, remainingCount)} more
        </Button>
      )}
      <p className="text-center text-xs text-slate-500">
        Showing {visiblePassengers.length} of {passengers.length} passengers
      </p>
    </div>
  );
});

function AttendanceDetailsCard({
  groupId,
  details,
  isLoading,
  isError,
  onRetry,
}: {
  groupId: string;
  details?: {
    missing_passengers: AttendancePassengerStatus[];
    scanned_passengers: AttendancePassengerStatus[];
    scanned_count: number;
    assigned_count: number;
  };
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}) {
  return (
    <div className="mt-3 space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-16 rounded-lg" />
          <Skeleton className="h-16 rounded-lg" />
        </div>
      ) : isError || !details ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700">
          <p>Details are not available offline yet. Connect once to refresh this activity.</p>
          <button
            type="button"
            className="mt-2 min-h-11 rounded-lg border border-amber-300 bg-white px-3 font-semibold text-amber-800"
            onClick={onRetry}
          >
            Try again
          </button>
        </div>
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
          prefetch={false}
          className="group block min-h-11 rounded-lg border border-white/60 bg-white/80 p-2 transition-colors hover:border-blue-200 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
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
