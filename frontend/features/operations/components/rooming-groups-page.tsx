"use client";

import Link from "next/link";
import { BedDouble, ChevronRight, Hotel, MapPin, UsersRound } from "lucide-react";
import { Card, CardContent, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/shared/page-header";
import { ROUTES } from "@/constants/routes";
import { useTourGroups } from "../hooks/use-operations";

export function RoomingGroupsPage() {
  const { data: groups = [], isLoading, error } = useTourGroups();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Rooming Lists"
        description="Allocate confirmed passengers into hotel rooms and export hotel-ready rooming lists."
      />

      {error && <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">Rooming groups could not be loaded.</div>}

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-36" />)}
        </div>
      ) : groups.length === 0 ? (
        <Card><CardContent className="p-10 text-center text-sm text-slate-500">No active groups are available for rooming allocation.</CardContent></Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {groups.map((group) => (
            <Link key={group.id} href={ROUTES.dashboard.roomingGroup(group.id) as never} className="group">
              <Card className="h-full transition-shadow hover:shadow-md">
                <CardContent className="p-5">
                  <div className="flex items-start justify-between gap-4">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600 ring-1 ring-blue-100">
                      <BedDouble className="h-5 w-5" aria-hidden="true" />
                    </span>
                    <ChevronRight className="h-5 w-5 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-blue-600" aria-hidden="true" />
                  </div>
                  <h2 className="mt-4 truncate font-semibold text-slate-900">{group.name}</h2>
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-slate-500">
                    <span className="inline-flex items-center gap-1.5"><UsersRound className="h-3.5 w-3.5" />{group.passenger_count} passengers</span>
                    {group.destination && <span className="inline-flex max-w-full items-center gap-1.5 truncate"><MapPin className="h-3.5 w-3.5 shrink-0" />{group.destination}</span>}
                    {group.travel_date && <span className="inline-flex items-center gap-1.5"><Hotel className="h-3.5 w-3.5" />{group.travel_date}</span>}
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
