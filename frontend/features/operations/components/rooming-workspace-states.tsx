"use client";

import type { ReactNode } from "react";
import { Hotel, Plus } from "lucide-react";
import { Button, Card, CardContent, Skeleton } from "@/components/ui";

export function HeaderContext({
  icon: Icon,
  children,
}: {
  icon: typeof Hotel;
  children: ReactNode;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-2.5 py-1 text-xs font-medium text-slate-200">
      <Icon className="h-3.5 w-3.5 text-sky-300" aria-hidden="true" />
      {children}
    </span>
  );
}

export function EmptyRoomingState({
  passengerCount,
  onCreate,
}: {
  passengerCount: number;
  onCreate: () => void;
}) {
  return (
    <Card>
      <CardContent className="p-10 text-center sm:p-12">
        <Hotel
          className="mx-auto h-10 w-10 text-blue-500"
          aria-hidden="true"
        />
        <h2 className="mt-4 text-lg font-semibold text-slate-900">
          Add the first hotel stay
        </h2>
        <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-slate-500">
          {passengerCount} confirmed passenger
          {passengerCount === 1 ? " is" : "s are"} ready. Add a hotel, choose
          who stays there, mark any VIPs, and auto-allocate rooms.
        </p>
        <Button type="button" className="mt-5" onClick={onCreate}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          Add hotel
        </Button>
      </CardContent>
    </Card>
  );
}

export function RoomingLoading() {
  return (
    <div className="space-y-5" aria-label="Loading rooming workspace">
      <Skeleton className="h-36 rounded-2xl" />
      <Skeleton className="h-[72px] rounded-xl" />
      <Skeleton className="h-16 rounded-xl" />
      <Skeleton className="h-32 rounded-xl" />
      <Skeleton className="h-96" />
    </div>
  );
}

export function CheckinLoading() {
  return (
    <div className="space-y-4" role="status" aria-label="Loading hotel check-in desk">
      <Skeleton className="h-16 rounded-xl" />
      <Skeleton className="h-24 rounded-xl" />
      <Skeleton className="h-72 rounded-xl" />
    </div>
  );
}
