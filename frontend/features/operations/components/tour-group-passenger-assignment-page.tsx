"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowLeft, Search } from "lucide-react";
import { Badge, Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/shared/page-header";
import { ROUTES } from "@/constants/routes";
import {
  useAssignTourGroupPassengers,
  useTourGroupPassengers,
  useTourGroups,
} from "../hooks/use-operations";
import {
  filterTourPassengers,
  PassengerAssignMenu,
  PassengerSelectionTable,
  TourEmptyState,
  TourMetric,
} from "./tour-operations-ui";

export function TourGroupPassengerAssignmentPage({ groupId }: { groupId: string }) {
  const { data: groups = [], isLoading: groupsLoading, error: groupsError } = useTourGroups();
  const { data: passengers = [], isLoading: passengersLoading, error: passengersError } = useTourGroupPassengers(groupId);
  const assignPassengers = useAssignTourGroupPassengers();
  const [selectedPassengerIds, setSelectedPassengerIds] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const group = groups.find((item) => item.id === groupId) ?? null;
  const filteredPassengers = useMemo(() => filterTourPassengers(passengers, query), [passengers, query]);

  const togglePassenger = (passengerId: string) => {
    setSelectedPassengerIds((current) =>
      current.includes(passengerId)
        ? current.filter((id) => id !== passengerId)
        : [...current, passengerId],
    );
  };

  const assignSelectedPassengers = (coordinatorId: string | null) => {
    if (selectedPassengerIds.length === 0) return;
    assignPassengers.mutate(
      { groupId, passengerIds: selectedPassengerIds, coordinatorId },
      { onSuccess: () => setSelectedPassengerIds([]) },
    );
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title={group?.name ?? "Group Passengers"}
        description="Assign submitted passengers only to coordinators already assigned to this group."
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

      {(groupsError || passengersError) && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Passenger assignment data could not be loaded.
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-4">
        {groupsLoading ? (
          Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-[90px] rounded-xl" />)
        ) : (
          <>
            <TourMetric label="Total People" value={group?.passenger_count ?? passengers.length} />
            <TourMetric label="Coordinators" value={group?.coordinators.length ?? 0} />
            <TourMetric label="Assigned" value={group?.assigned_passengers_count ?? 0} />
            <TourMetric label="Unassigned" value={group?.unassigned_passengers_count ?? 0} tone={(group?.unassigned_passengers_count ?? 0) > 0 ? "warning" : "default"} />
          </>
        )}
      </div>

      {group && group.coordinators.length === 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          Assign coordinators to this group before splitting passengers.
        </div>
      )}

      <Card>
        <CardContent className="space-y-4 p-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-base font-semibold text-slate-900">Passengers</h2>
                {group?.status && <Badge variant={group.status === "active" ? "success" : "outline"}>{group.status}</Badge>}
              </div>
              <p className="mt-1 text-sm text-slate-500">
                {selectedPassengerIds.length} selected. Use the assign menu to split selected passengers.
              </p>
            </div>
            <PassengerAssignMenu
              coordinators={group?.coordinators ?? []}
              selectedCount={selectedPassengerIds.length}
              disabled={assignPassengers.isPending || selectedPassengerIds.length === 0 || !group || group.coordinators.length === 0}
              onAssign={assignSelectedPassengers}
            />
          </div>

          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="relative md:w-96">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
              <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search passengers" className="pl-9" />
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setSelectedPassengerIds(filteredPassengers.map((passenger) => passenger.id))}
                disabled={filteredPassengers.length === 0}
              >
                Select visible
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => setSelectedPassengerIds([])} disabled={selectedPassengerIds.length === 0}>
                Clear
              </Button>
            </div>
          </div>

          {passengersLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-12 rounded-lg" />)}
            </div>
          ) : filteredPassengers.length === 0 ? (
            <TourEmptyState>No submitted passengers found for this group.</TourEmptyState>
          ) : (
            <PassengerSelectionTable passengers={filteredPassengers} selectedIds={selectedPassengerIds} onToggle={togglePassenger} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
