"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, type ReactNode } from "react";
import { ArrowLeft, CloudOff, LogIn, Mail, MapPin, Phone, RefreshCw, UserRound } from "lucide-react";
import { Button, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { useMyTourGroupPassenger } from "@/features/operations/hooks/use-operations";
import {
  selectHasHydrated,
  selectIsAuthenticated,
  selectUser,
  useAuthStore,
} from "@/stores/auth.store";
import { CoordinatorFrame, CoordinatorHydrationState } from "./coordinator-mobile-shell";
import {
  offlineSnapshotKeys,
  readOfflineSnapshot,
  writeOfflineSnapshot,
} from "../services/offline-snapshot";
import {
  sanitizeOfflinePassengerSnapshots,
  toOfflinePassengerSnapshot,
  type OfflinePassengerSnapshot,
} from "../services/passenger-offline-projection";
import { useNetworkStatus } from "../hooks/use-network-status";

export function CoordinatorPassengerDetailPage({ groupId, passengerId }: { groupId: string; passengerId: string }) {
  const router = useRouter();
  const user = useAuthStore(selectUser);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const hasHydrated = useAuthStore(selectHasHydrated);
  const clearSession = useAuthStore((state) => state.clearSession);
  const isOnline = useNetworkStatus();
  const isCoordinator = isAuthenticated && user?.role === "agency_coordinator";
  const userId = user?.id;
  const passengerQuery = useMyTourGroupPassenger(
    groupId,
    passengerId,
    hasHydrated && isCoordinator,
  );
  const passengerSnapshotKey = offlineSnapshotKeys.myPassengers(groupId);
  const cachedPassengers = useMemo<OfflinePassengerSnapshot[]>(
    () => userId
      ? sanitizeOfflinePassengerSnapshots(
          readOfflineSnapshot<unknown>(passengerSnapshotKey, []),
        )
      : [],
    [passengerSnapshotKey, userId],
  );
  const cachedPassenger = cachedPassengers.find((item) => item.id === passengerId) ?? null;
  const passenger = passengerQuery.data ?? cachedPassenger;
  const isShowingSavedPassenger = !passengerQuery.isSuccess && Boolean(cachedPassenger);

  useEffect(() => {
    if (!userId) return;
    writeOfflineSnapshot(passengerSnapshotKey, cachedPassengers);
  }, [cachedPassengers, passengerSnapshotKey, userId]);

  useEffect(() => {
    if (!passengerQuery.isSuccess || !passengerQuery.data) return;
    const offlinePassenger = toOfflinePassengerSnapshot(passengerQuery.data);
    const nextPassengers = cachedPassengers.some((item) => item.id === offlinePassenger.id)
      ? cachedPassengers.map((item) => item.id === offlinePassenger.id ? offlinePassenger : item)
      : [...cachedPassengers, offlinePassenger];
    writeOfflineSnapshot(passengerSnapshotKey, nextPassengers);
  }, [
    cachedPassengers,
    passengerQuery.data,
    passengerQuery.isSuccess,
    passengerSnapshotKey,
  ]);

  if (!hasHydrated) {
    return <CoordinatorHydrationState label="Loading passenger details" />;
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
            Sign in with a coordinator account to view passenger details.
          </p>
          <Button
            type="button"
            className="mt-6 h-12 w-full"
            onClick={() => {
              if (isAuthenticated) {
                void clearSession();
                return;
              }
              router.push(
                ROUTES.auth.coordinatorLogin(
                  `/coordinator/groups/${groupId}/passengers/${passengerId}`,
                ) as never,
              );
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
        <Link
          href={`/coordinator/groups/${groupId}` as never}
          className="mb-3 inline-flex min-h-11 items-center gap-2 rounded-lg pr-3 text-sm font-medium text-slate-600"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Back to activity
        </Link>
        <p className="text-xs font-semibold uppercase text-blue-600">Passenger Details</p>
        <h1 className="mt-1 break-words text-xl font-bold text-slate-950">{passenger?.client_name ?? "Passenger"}</h1>
      </header>

      <main className="flex-1 space-y-4 px-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
        {!isOnline && (
          <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            <CloudOff className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            {isShowingSavedPassenger
              ? "Offline: showing the latest passenger details saved on this device."
              : "Offline: reconnect to load passenger details."}
          </div>
        )}
        {passengerQuery.isLoading && !passenger ? (
          <div className="space-y-3">
            <Skeleton className="h-28 rounded-xl" />
            <Skeleton className="h-44 rounded-xl" />
            <Skeleton className="h-32 rounded-xl" />
          </div>
        ) : !passenger ? (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            <p>Passenger details could not be loaded. Check the connection and try again.</p>
            <Button
              type="button"
              variant="secondary"
              className="mt-3 h-11 w-full"
              isLoading={passengerQuery.isFetching}
              leftIcon={<RefreshCw className="h-4 w-4" aria-hidden="true" />}
              onClick={() => void passengerQuery.refetch()}
            >
              Try again
            </Button>
          </div>
        ) : (
          <>
            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-start gap-3">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-blue-50 text-blue-600">
                  <UserRound className="h-6 w-6" aria-hidden="true" />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="break-words text-lg font-bold text-slate-950">{passenger.client_name}</h2>
                  <p className="mt-1 text-sm text-slate-500">
                    {passenger.departure_city ? `Departure city: ${passenger.departure_city}` : "No departure city"}
                  </p>
                </div>
              </div>
            </section>

            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="text-base font-semibold text-slate-950">Contact</h2>
              <div className="mt-3 space-y-3">
                <InfoRow icon={<Phone className="h-4 w-4" />} label="Phone" value={passenger.client_phone} />
                <InfoRow icon={<Mail className="h-4 w-4" />} label="Email" value={passenger.client_email} />
                <InfoRow icon={<MapPin className="h-4 w-4" />} label="Departure city" value={passenger.departure_city} />
              </div>
            </section>
          </>
        )}
      </main>
    </CoordinatorFrame>
  );
}

function InfoRow({ icon, label, value }: { icon: ReactNode; label: string; value?: string | null }) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-slate-100 bg-slate-50 p-3">
      <span className="mt-0.5 text-slate-400">{icon}</span>
      <div className="min-w-0">
        <p className="text-[11px] font-semibold uppercase text-slate-500">{label}</p>
        <p className="mt-0.5 break-words text-sm font-medium text-slate-900 [overflow-wrap:anywhere]">{value || "Not available"}</p>
      </div>
    </div>
  );
}
