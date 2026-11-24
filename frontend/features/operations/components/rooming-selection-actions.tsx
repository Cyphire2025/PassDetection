"use client";

import { Crown, Hotel } from "lucide-react";
import { Button, Input } from "@/components/ui";
import type { RoomingPassengerSelection } from "../hooks/use-rooming-passenger-selection";
import type { RoomingPassengerHotelAllocationProps } from "../types/rooming-passenger-selection";

export function RoomingSelectionActions({ selection, workspace, activeHotel, isAssigning, isUpdatingVip }: {
  selection: RoomingPassengerSelection;
} & Pick<RoomingPassengerHotelAllocationProps, "workspace" | "activeHotel" | "isAssigning" | "isUpdatingVip">) {
  const { pending, visiblePassengers, validSelectedPassengerIds, selectedAtActiveHotel,
    firstCount, setFirstCount, validFirstCount, setSelectedPassengerIds,
    selectVisible, selectFirst, effectiveTargetHotelId, setTargetHotelId,
    assignSelected, setVip, actionError, actionStatus } = selection;
  return (
    <>
      <div className="flex flex-wrap items-end gap-2">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={selectVisible}
          disabled={pending || visiblePassengers.length === 0}
        >
          Select visible
        </Button>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() =>
            setSelectedPassengerIds(
              new Set(
                workspace.passengers.map(
                  (passenger) => passenger.passenger_id,
                ),
              ),
            )
          }
          disabled={pending || workspace.passengers.length === 0}
        >
          Select all group
        </Button>
        <div className="flex items-end gap-2">
          <Input
            id="rooming-select-first-count"
            label="First passengers"
            type="number"
            min="1"
            max={Math.max(1, visiblePassengers.length)}
            inputMode="numeric"
            value={firstCount}
            onChange={(event) => setFirstCount(event.target.value)}
            className="w-24"
            disabled={pending}
          />
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={selectFirst}
            disabled={
              pending ||
              !validFirstCount ||
              visiblePassengers.length === 0
            }
          >
            Select first
          </Button>
        </div>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => setSelectedPassengerIds(new Set())}
          disabled={pending || validSelectedPassengerIds.length === 0}
        >
          Clear selection
        </Button>
      </div>

      <div className="grid gap-3 rounded-xl border border-slate-200 bg-white p-3 xl:grid-cols-[minmax(220px,1fr)_auto_auto] xl:items-end">
        <label className="block text-sm font-medium text-slate-700">
          Assign selected passengers to
          <select
            value={effectiveTargetHotelId}
            onChange={(event) => setTargetHotelId(event.target.value)}
            disabled={pending}
            className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:opacity-60"
          >
            {workspace.hotels.map((hotel) => (
              <option key={hotel.id} value={hotel.id}>
                {hotel.hotel_name}
              </option>
            ))}
          </select>
        </label>
        <Button
          type="button"
          onClick={() => void assignSelected()}
          isLoading={isAssigning}
          disabled={
            validSelectedPassengerIds.length === 0 || isUpdatingVip
          }
        >
          <Hotel className="h-4 w-4" aria-hidden="true" />
          Assign selected
        </Button>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="secondary"
            onClick={() => void setVip(true)}
            isLoading={isUpdatingVip}
            disabled={isAssigning || selectedAtActiveHotel.length === 0}
            title={`Applies to selected passengers staying at ${activeHotel.hotel_name}`}
          >
            <Crown
              className="h-4 w-4 text-amber-600"
              aria-hidden="true"
            />
            Mark VIP ({selectedAtActiveHotel.length})
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => void setVip(false)}
            isLoading={isUpdatingVip}
            disabled={isAssigning || selectedAtActiveHotel.length === 0}
            title={`Applies to selected passengers staying at ${activeHotel.hotel_name}`}
          >
            Remove VIP
          </Button>
        </div>
      </div>

      <p className="text-xs leading-5 text-slate-500">
        VIP actions apply only to selected passengers already staying at{" "}
        <strong className="font-semibold text-slate-700">
          {activeHotel.hotel_name}
        </strong>
        . VIP passengers always receive a single room during auto
        allocation.
      </p>

      {actionError && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {actionError}
        </div>
      )}
      {actionStatus && (
        <div
          role="status"
          className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"
        >
          {actionStatus}
        </div>
      )}
    </>
  );
}
