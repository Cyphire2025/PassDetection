"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, UserCheck } from "lucide-react";
import { Badge, Button, Card, CardContent } from "@/components/ui";
import { cn } from "@/lib/utils/cn";
import type { TourCoordinator, TourGroup, TourPassenger } from "../api/operations.api";

export function TourMetric({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: number;
  tone?: "default" | "warning";
}) {
  return (
    <Card className={tone === "warning" ? "border-amber-200 bg-amber-50" : undefined}>
      <CardContent className="p-4">
        <p className="text-xs font-medium uppercase text-slate-500">{label}</p>
        <p className="mt-1 text-2xl font-bold text-slate-900">{value}</p>
      </CardContent>
    </Card>
  );
}

export function TourEmptyState({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-lg border border-dashed border-slate-300 px-3 py-8 text-center text-sm text-slate-500">
      {children}
    </p>
  );
}

export function getTourGroupTotals(groups: TourGroup[]) {
  return groups.reduce(
    (totals, group) => ({
      groups: totals.groups + 1,
      passengers: totals.passengers + group.passenger_count,
      assigned: totals.assigned + group.assigned_passengers_count,
      unassigned: totals.unassigned + group.unassigned_passengers_count,
      unassignedGroups: totals.unassignedGroups + (group.coordinators.length === 0 ? 1 : 0),
    }),
    { groups: 0, passengers: 0, assigned: 0, unassigned: 0, unassignedGroups: 0 },
  );
}

export function filterTourPassengers(passengers: TourPassenger[], query: string) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return passengers;

  return passengers.filter((passenger) =>
    [passenger.client_name, passenger.client_email, passenger.client_phone, passenger.coordinator_name]
      .filter(Boolean)
      .some((value) => value?.toLowerCase().includes(normalized)),
  );
}

export function CoordinatorMultiSelect({
  coordinators,
  selectedIds,
  disabled,
  onToggle,
}: {
  coordinators: TourCoordinator[];
  selectedIds: string[];
  disabled?: boolean;
  onToggle: (coordinatorId: string, checked: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useCloseOnOutsideClick(() => setOpen(false));

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        className={cn(
          "flex h-11 w-full items-center justify-between rounded-lg border px-3 text-sm font-medium shadow-sm transition disabled:opacity-60",
          selectedIds.length > 0
            ? "border-blue-200 bg-blue-50 text-blue-800 hover:border-blue-300"
            : "border-slate-300 bg-white text-slate-700 hover:border-slate-400",
        )}
      >
        <span>{selectedIds.length === 0 ? "Assign coordinators" : `${selectedIds.length} coordinator${selectedIds.length === 1 ? "" : "s"}`}</span>
        <ChevronDown className="h-4 w-4 text-slate-400" aria-hidden="true" />
      </button>

      {open && (
        <div className="absolute z-30 mt-2 max-h-72 w-full min-w-80 overflow-y-auto rounded-lg border border-slate-200 bg-white p-2 shadow-xl ring-1 ring-slate-900/5">
          {coordinators.length === 0 ? (
            <p className="px-3 py-2 text-sm text-slate-500">Create a coordinator first.</p>
          ) : (
            coordinators.map((coordinator) => {
              const selected = selectedIds.includes(coordinator.id);
              return (
                <button
                  key={coordinator.id}
                  type="button"
                  onClick={() => onToggle(coordinator.id, !selected)}
                  className={cn(
                    "flex w-full items-center justify-between gap-3 rounded-md px-3 py-2.5 text-left text-sm",
                    selected ? "bg-blue-50 text-blue-800" : "text-slate-700 hover:bg-slate-50",
                  )}
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{coordinator.full_name}</span>
                    <span className="block truncate text-xs text-slate-500">{coordinator.email}</span>
                  </span>
                  <span className={cn("flex h-5 w-5 shrink-0 items-center justify-center rounded border", selected ? "border-blue-600 bg-blue-600 text-white" : "border-slate-300 bg-white")}>
                    {selected && <Check className="h-3.5 w-3.5" aria-hidden="true" />}
                  </span>
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}

export function PassengerAssignMenu({
  coordinators,
  selectedCount,
  disabled,
  onAssign,
}: {
  coordinators: TourGroup["coordinators"];
  selectedCount: number;
  disabled?: boolean;
  onAssign: (coordinatorId: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useCloseOnOutsideClick(() => setOpen(false));

  return (
    <div className="relative" ref={ref}>
      <Button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        leftIcon={<UserCheck className="h-4 w-4" aria-hidden="true" />}
      >
        Assign{selectedCount > 0 ? ` ${selectedCount}` : ""}
      </Button>

      {open && (
        <div className="absolute right-0 z-30 mt-2 w-72 rounded-lg border border-slate-200 bg-white p-2 shadow-xl">
          {coordinators.length === 0 ? (
            <p className="px-3 py-2 text-sm text-slate-500">Assign coordinators to this group first.</p>
          ) : (
            coordinators.map((coordinator) => (
              <button
                key={coordinator.coordinator_id}
                type="button"
                onClick={() => {
                  onAssign(coordinator.coordinator_id);
                  setOpen(false);
                }}
                className="flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-sm text-slate-700 hover:bg-blue-50 hover:text-blue-800"
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium">{coordinator.full_name}</span>
                  <span className="block text-xs text-slate-500">{coordinator.assigned_passengers_count} passengers</span>
                </span>
                <Check className="h-4 w-4 shrink-0 opacity-0" aria-hidden="true" />
              </button>
            ))
          )}
          <button
            type="button"
            onClick={() => {
              onAssign(null);
              setOpen(false);
            }}
            className="mt-1 flex w-full items-center rounded-md px-3 py-2 text-left text-sm text-red-700 hover:bg-red-50"
          >
            Remove assignment
          </button>
        </div>
      )}
    </div>
  );
}

export function PassengerSelectionTable({
  passengers,
  selectedIds,
  onToggle,
}: {
  passengers: TourPassenger[];
  selectedIds: string[];
  onToggle: (passengerId: string) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="w-full min-w-[760px] text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase text-slate-500">
          <tr>
            <th className="w-12 px-4 py-3">Select</th>
            <th className="px-4 py-3">Passenger</th>
            <th className="px-4 py-3">Contact</th>
            <th className="px-4 py-3">Coordinator</th>
            <th className="px-4 py-3">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {passengers.map((passenger) => {
            const selected = selectedIds.includes(passenger.id);
            return (
              <tr
                key={passenger.id}
                className={cn("cursor-pointer hover:bg-slate-50", selected && "bg-blue-50 hover:bg-blue-50")}
                onClick={() => onToggle(passenger.id)}
              >
                <td className="px-4 py-3">
                  <span className={cn("flex h-5 w-5 items-center justify-center rounded border", selected ? "border-blue-600 bg-blue-600 text-white" : "border-slate-300 bg-white")}>
                    {selected && <Check className="h-3.5 w-3.5" aria-hidden="true" />}
                  </span>
                </td>
                <td className="px-4 py-3 font-medium text-slate-900">{passenger.client_name}</td>
                <td className="px-4 py-3 text-slate-600">
                  {[passenger.client_email, passenger.client_phone].filter(Boolean).join(" | ") || "No contact"}
                </td>
                <td className="px-4 py-3">
                  <Badge variant={passenger.coordinator_id ? "secondary" : "outline"}>
                    {passenger.coordinator_name ?? "Unassigned"}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-slate-600">{passenger.status.replaceAll("_", " ")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function useCloseOnOutsideClick(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handlePointerDown(event: PointerEvent) {
      if (!ref.current || ref.current.contains(event.target as Node)) return;
      onClose();
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [onClose]);

  return ref;
}
