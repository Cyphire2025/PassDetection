"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { ArrowLeft, LogIn, Mail, MapPin, Phone, UserRound } from "lucide-react";
import { Button, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { useMyTourGroupPassenger } from "@/features/operations/hooks/use-operations";
import { selectIsAuthenticated, selectUser, useAuthStore } from "@/stores/auth.store";
import { CoordinatorFrame } from "./coordinator-mobile-shell";

export function CoordinatorPassengerDetailPage({ groupId, passengerId }: { groupId: string; passengerId: string }) {
  const router = useRouter();
  const user = useAuthStore(selectUser);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const clearSession = useAuthStore((state) => state.clearSession);
  const isCoordinator = isAuthenticated && user?.role === "agency_coordinator";
  const { data: passenger, isLoading, error } = useMyTourGroupPassenger(groupId, passengerId, isCoordinator);

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
        <Link
          href={`/coordinator/groups/${groupId}` as never}
          className="mb-4 inline-flex items-center gap-2 text-sm font-medium text-slate-600"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Back to activity
        </Link>
        <p className="text-xs font-semibold uppercase text-blue-600">Passenger Details</p>
        <h1 className="mt-1 truncate text-xl font-bold text-slate-950">{passenger?.client_name ?? "Passenger"}</h1>
      </header>

      <main className="flex-1 space-y-4 px-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
        {isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-28 rounded-xl" />
            <Skeleton className="h-44 rounded-xl" />
            <Skeleton className="h-32 rounded-xl" />
          </div>
        ) : error || !passenger ? (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            Passenger details could not be loaded. Check internet connection and try again.
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
        <p className="mt-0.5 break-words text-sm font-medium text-slate-900">{value || "Not available"}</p>
      </div>
    </div>
  );
}
