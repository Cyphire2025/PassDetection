"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo } from "react";
import { ArrowLeft, CloudOff, LogIn, RefreshCw, UsersRound, Wifi } from "lucide-react";
import { Badge, Button, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import {
  selectHasHydrated,
  selectIsAuthenticated,
  selectUser,
  useAuthStore,
} from "@/stores/auth.store";
import { useMyTourGroups } from "@/features/operations/hooks/use-operations";
import type { TourGroup } from "@/features/operations/api/operations.api";
import { offlineSnapshotKeys, readOfflineSnapshot, writeOfflineSnapshot } from "../services/offline-snapshot";
import { useNetworkStatus } from "../hooks/use-network-status";

const EMPTY_GROUPS: TourGroup[] = [];

export function CoordinatorMobileShell() {
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
  const isShowingSavedGroups = !groupsQuery.isSuccess && cachedGroups.length > 0;
  const totalPeople = useMemo(
    () => visibleGroups.reduce((sum, group) => sum + group.assigned_passengers_count, 0),
    [visibleGroups],
  );

  useEffect(() => {
    if (!groupsQuery.isSuccess) return;
    writeOfflineSnapshot(offlineSnapshotKeys.myGroups, groups);
  }, [groups, groupsQuery.isSuccess]);

  if (!hasHydrated) {
    return <CoordinatorHydrationState label="Checking coordinator access" />;
  }

  if (!isAuthenticated || !isCoordinator) {
    const title = isAuthenticated ? "Coordinator login required" : "Sign in required";
    const description = isAuthenticated
      ? `Current account is ${user?.role.replaceAll("_", " ") ?? "not a coordinator"}. Sign in with a coordinator account to use the PWA scanner.`
      : "Coordinator groups and passenger lists are available after login.";
    return (
      <CoordinatorFrame>
        <div className="flex flex-1 flex-col items-center justify-center px-5 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-50 text-blue-600">
            <LogIn className="h-7 w-7" aria-hidden="true" />
          </div>
          <h1 className="mt-5 text-xl font-bold text-slate-950">{title}</h1>
          <p className="mt-2 text-sm leading-6 text-slate-500">{description}</p>
          <div className="mt-6 grid w-full max-w-sm gap-3">
            <Button
              type="button"
              className="h-12 w-full"
              onClick={() => {
                if (isAuthenticated) {
                  void clearSession();
                  return;
                }
                router.push(ROUTES.auth.coordinatorLogin() as never);
              }}
            >
              {isAuthenticated ? "Switch Account" : "Login"}
            </Button>
            {isAuthenticated && (
              <Button
                type="button"
                variant="secondary"
                className="h-12 w-full"
                onClick={() => router.push(ROUTES.dashboard.root as never)}
              >
                Back to Dashboard
              </Button>
            )}
          </div>
        </div>
      </CoordinatorFrame>
    );
  }

  return (
    <CoordinatorFrame>
      <header className="px-4 pb-4 pt-[max(1rem,env(safe-area-inset-top))]">
        <Link href={ROUTES.dashboard.root as never} className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-700 shadow-sm">
          <ArrowLeft className="h-5 w-5" aria-hidden="true" />
          <span className="sr-only">Back to dashboard</span>
        </Link>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase text-blue-600">Tour Operations</p>
            <h1 className="mt-1 truncate text-xl font-bold text-slate-950">{user?.full_name ?? "Coordinator"}</h1>
          </div>
          <Badge variant={isOnline ? "secondary" : "warning"}>
            {isOnline ? <Wifi className="h-3 w-3" aria-hidden="true" /> : <CloudOff className="h-3 w-3" aria-hidden="true" />}
            {isOnline ? "Online" : "Offline"}
          </Badge>
        </div>
      </header>

      <main className="flex-1 space-y-4 px-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
        <section className="grid grid-cols-2 gap-3">
          <Metric label="Groups" value={visibleGroups.length} />
          <Metric label="People" value={totalPeople} />
        </section>

        {groupsQuery.error && (
          <div className={`rounded-xl border p-4 text-sm ${isShowingSavedGroups ? "border-amber-200 bg-amber-50 text-amber-800" : "border-red-200 bg-red-50 text-red-700"}`}>
            <p>
              {isShowingSavedGroups
                ? "Showing saved groups while the latest data is unavailable."
                : "Assigned tour groups could not be loaded."}
            </p>
            <Button
              type="button"
              variant="secondary"
              className="mt-3 h-11 w-full"
              isLoading={groupsQuery.isFetching}
              leftIcon={<RefreshCw className="h-4 w-4" aria-hidden="true" />}
              onClick={() => void groupsQuery.refetch()}
            >
              Try again
            </Button>
          </div>
        )}

        <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 p-4">
            <h2 className="text-base font-semibold text-slate-950">Assigned Groups</h2>
            <p className="mt-1 text-sm text-slate-500">Tap a group to start or continue an activity.</p>
          </div>
          <div className="space-y-2 p-3">
            {groupsQuery.isLoading && visibleGroups.length === 0 ? (
              Array.from({ length: 3 }).map((_, index) => <Skeleton key={index} className="h-16 rounded-lg" />)
            ) : visibleGroups.length === 0 ? (
              <p className="rounded-lg border border-dashed border-slate-300 px-3 py-6 text-center text-sm text-slate-500">
                No groups assigned yet.
              </p>
            ) : (
              visibleGroups.map((group) => <GroupLink key={group.id} group={group} />)
            )}
          </div>
        </section>
      </main>
    </CoordinatorFrame>
  );
}

export function CoordinatorFrame({ children }: { children: React.ReactNode }) {
  return (
    <div
      data-coordinator-shell
      className="bg-slate-100 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] text-slate-950"
    >
      <div className="mx-auto flex min-h-dvh w-full max-w-lg flex-col bg-slate-50 sm:border-x sm:border-slate-200">
        {children}
      </div>
    </div>
  );
}

export function CoordinatorHydrationState({ label = "Loading coordinator workspace" }: { label?: string }) {
  return (
    <CoordinatorFrame>
      <div className="flex flex-1 flex-col px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-[max(1rem,env(safe-area-inset-top))]">
        <div className="flex items-center justify-between">
          <Skeleton className="h-11 w-11 rounded-full" />
          <Skeleton className="h-6 w-20 rounded-full" />
        </div>
        <Skeleton className="mt-5 h-6 w-48 rounded-md" />
        <Skeleton className="mt-2 h-4 w-64 max-w-full rounded-md" />
        <div className="mt-6 grid grid-cols-2 gap-3">
          <Skeleton className="h-20 rounded-xl" />
          <Skeleton className="h-20 rounded-xl" />
        </div>
        <Skeleton className="mt-4 h-52 rounded-xl" />
        <p className="sr-only" role="status">{label}</p>
      </div>
    </CoordinatorFrame>
  );
}

function GroupLink({ group }: { group: TourGroup }) {
  return (
    <Link
      href={`/coordinator/groups/${group.id}` as never}
      className="block min-h-16 rounded-lg border border-slate-200 bg-white p-3 text-left transition-colors hover:border-blue-300 hover:bg-blue-50 active:bg-blue-100"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-950">{group.name}</p>
          <p className="mt-0.5 truncate text-xs text-slate-500">
            {[group.destination, group.travel_date].filter(Boolean).join(" | ") || "No trip details"}
          </p>
        </div>
        <Badge variant={group.status === "active" ? "success" : "outline"}>{group.status}</Badge>
      </div>
      <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
        <UsersRound className="h-4 w-4" aria-hidden="true" />
        {group.assigned_passengers_count} people assigned
      </div>
    </Link>
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
