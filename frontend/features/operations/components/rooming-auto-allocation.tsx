"use client";

import {
  AlertTriangle,
  BedDouble,
  Crown,
  Download,
  ListOrdered,
  Sparkles,
  X,
} from "lucide-react";
import { memo, useMemo, useState } from "react";
import { Badge, Button, Card, CardContent } from "@/components/ui";
import type {
  RoomingHotel,
  RoomingPriorityField,
  RoomingPriorityFieldOptions,
  RoomingRoom,
} from "../api/operations.api";
import { normalizeRoomingGender } from "./rooming-passenger-hotel-allocation";
import { roomingErrorMessage } from "./rooming-error-message";
import { isRoomingPriorityFieldAllowed } from "./rooming-priority-field-policy.mjs";

const MAX_PRIORITY_SLOTS = 6;

interface RoomingAutoAllocationProps {
  activeHotel: RoomingHotel;
  options: RoomingPriorityFieldOptions | undefined;
  optionsLoading: boolean;
  optionsError: boolean;
  isAllocating: boolean;
  isExporting: boolean;
  onAutoAllocate: (priorityFields: string[]) => Promise<void>;
  onExport: () => Promise<void>;
}

export function RoomingAutoAllocation({
  activeHotel,
  options,
  optionsLoading,
  optionsError,
  isAllocating,
  isExporting,
  onAutoAllocate,
  onExport,
}: RoomingAutoAllocationProps) {
  const [prioritySlots, setPrioritySlots] = useState<Array<string | null>>(
    createPrioritySlots(activeHotel.allocation_priority_fields),
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionStatus, setActionStatus] = useState<string | null>(null);

  const allowedFields = useMemo(
    () => (options?.fields ?? []).filter(isRoomingPriorityFieldAllowed),
    [options?.fields],
  );
  const allowedByKey = useMemo(
    () => new Map(allowedFields.map((field) => [field.key, field])),
    [allowedFields],
  );
  const currentPrioritySlots = useMemo(
    () => (
      options
        ? sanitizePrioritySlots(prioritySlots, allowedByKey)
        : prioritySlots
    ),
    [allowedByKey, options, prioritySlots],
  );
  const unavailablePriorityFields = useMemo(() => {
    if (!options) return [];
    const unavailableKeys = new Set(
      prioritySlots.filter(
        (key): key is string => Boolean(key) && !allowedByKey.has(key as string),
      ),
    );
    return activeHotel.allocation_priority_fields.filter(
      (field) => unavailableKeys.has(field.key),
    );
  }, [
    activeHotel.allocation_priority_fields,
    allowedByKey,
    options,
    prioritySlots,
  ]);
  const chosenPriorities = useMemo(
    () => currentPrioritySlots.filter((key): key is string => Boolean(key)),
    [currentPrioritySlots],
  );
  const chosenPrioritySet = useMemo(
    () => new Set(chosenPriorities),
    [chosenPriorities],
  );
  const invalidGenderPassengers = useMemo(
    () => activeHotel.selected_passengers.filter(
      (passenger) => !normalizeRoomingGender(
        passenger.passport_sex,
      ),
    ),
    [activeHotel.selected_passengers],
  );
  const canAllocate = (
    activeHotel.selected_passenger_count > 0
    && invalidGenderPassengers.length === 0
    && !optionsLoading
    && !optionsError
    && !isAllocating
  );

  const choosePriority = (index: number, key: string) => {
    setPrioritySlots((current) => {
      const next = options
        ? sanitizePrioritySlots(current, allowedByKey)
        : [...current];
      next[index] = key || null;
      return compactPrioritySlots(next);
    });
    setActionStatus(null);
  };
  const runAllocation = async () => {
    if (!canAllocate) return;
    setActionError(null);
    setActionStatus(null);
    try {
      await onAutoAllocate(chosenPriorities);
      setActionStatus(
        `${activeHotel.selected_passenger_count} passenger${
          activeHotel.selected_passenger_count === 1 ? "" : "s"
        } auto-allocated for ${activeHotel.hotel_name}.`,
      );
    } catch (error) {
      setActionError(
        roomingErrorMessage(
          error,
          "Rooms could not be auto-allocated. Correct the highlighted passenger data and try again.",
        ),
      );
    }
  };

  return (
    <div className="space-y-5">
      <Card>
        <CardContent className="space-y-5 p-4 sm:p-6">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-violet-50 text-violet-700">
                <ListOrdered className="h-5 w-5" aria-hidden="true" />
              </span>
              <div>
                <h2 className="font-semibold text-slate-950">
                  2. Set auto-allocation priorities
                </h2>
                <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
                  Priority 1 creates the main passenger sections. Priorities
                  2-6 refine room pairs inside each section. Leave any slot
                  empty when that distinction does not matter.
                </p>
              </div>
            </div>
            <span className="w-fit rounded-full bg-violet-100 px-3 py-1.5 text-xs font-semibold text-violet-800">
              {chosenPriorities.length}/{MAX_PRIORITY_SLOTS} priorities
            </span>
          </div>

          {optionsError ? (
            <div
              role="alert"
              className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"
            >
              Allocation priority fields could not be loaded. Refresh this page
              before allocating rooms.
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {currentPrioritySlots.map((selectedKey, index) => {
                const selectedField = selectedKey
                  ? allowedByKey.get(selectedKey)
                  : undefined;
                return (
                  <div
                    key={index}
                    className="rounded-xl border border-slate-200 bg-slate-50 p-3"
                  >
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <label
                        htmlFor={`rooming-priority-${index}`}
                        className="text-xs font-bold uppercase tracking-wide text-slate-600"
                      >
                        Priority {index + 1}
                      </label>
                      {selectedKey && (
                        <button
                          type="button"
                          onClick={() => choosePriority(index, "")}
                          disabled={isAllocating}
                          className="rounded-md p-1 text-slate-400 hover:bg-white hover:text-slate-700 disabled:opacity-50"
                          aria-label={`Clear priority ${index + 1}`}
                        >
                          <X className="h-3.5 w-3.5" aria-hidden="true" />
                        </button>
                      )}
                    </div>
                    <select
                      id={`rooming-priority-${index}`}
                      value={selectedKey ?? ""}
                      onChange={(event) => choosePriority(index, event.target.value)}
                      disabled={optionsLoading || optionsError || isAllocating}
                      className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:opacity-60"
                    >
                      <option value="">
                        {optionsLoading ? "Loading fields..." : "No priority"}
                      </option>
                      {allowedFields.map((field) => (
                        <option
                          key={field.key}
                          value={field.key}
                          disabled={
                            chosenPrioritySet.has(field.key)
                            && field.key !== selectedKey
                          }
                        >
                          {field.label} - {prioritySourceLabel(field.source)}
                        </option>
                      ))}
                    </select>
                    <p className="mt-2 min-h-4 text-xs text-slate-500">
                      {selectedField
                        ? prioritySourceLabel(selectedField.source)
                        : "Optional"}
                    </p>
                  </div>
                );
              })}
            </div>
          )}

          {unavailablePriorityFields.length > 0 && (
            <div
              role="status"
              className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
            >
              {unavailablePriorityFields.length === 1
                ? "A previously saved priority is"
                : `${unavailablePriorityFields.length} previously saved priority fields are`}{" "}
              no longer available and{" "}
              {unavailablePriorityFields.length === 1 ? "has" : "have"} been
              removed from this draft:{" "}
              <strong>
                {unavailablePriorityFields.map((field) => field.label).join(", ")}
              </strong>
              . Review the six slots and run auto allocation again.
            </div>
          )}

          {invalidGenderPassengers.length > 0 && (
            <div
              role="alert"
              className="rounded-xl border border-red-300 bg-red-50 p-4"
            >
              <div className="flex items-start gap-3">
                <AlertTriangle
                  className="mt-0.5 h-5 w-5 shrink-0 text-red-700"
                  aria-hidden="true"
                />
                <div>
                  <h3 className="font-semibold text-red-950">
                    Correct Gender for {invalidGenderPassengers.length} passenger
                    {invalidGenderPassengers.length === 1 ? "" : "s"}
                  </h3>
                  <p className="mt-1 text-sm leading-6 text-red-800">
                    Auto allocation is blocked until every passenger assigned to
                    this hotel has Gender saved as Male or Female.
                  </p>
                  <p className="mt-2 text-xs font-semibold text-red-900">
                    {invalidGenderPassengers
                      .slice(0, 8)
                      .map((passenger) => passenger.client_name)
                      .join(", ")}
                    {invalidGenderPassengers.length > 8
                      ? `, and ${invalidGenderPassengers.length - 8} more`
                      : ""}
                  </p>
                </div>
              </div>
            </div>
          )}

          {activeHotel.selected_passenger_count === 0 && (
            <div className="rounded-xl border border-dashed border-slate-300 px-4 py-3 text-sm text-slate-600">
              Assign at least one passenger to {activeHotel.hotel_name} before
              auto allocation.
            </div>
          )}

          {actionError && (
            <div
              role="alert"
              className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            >
              {actionError}
            </div>
          )}
          {actionStatus && (
            <div
              role="status"
              className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"
            >
              {actionStatus}
            </div>
          )}

          <div className="flex flex-col gap-3 border-t border-slate-200 pt-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-sm text-slate-600">
              <strong className="font-semibold text-slate-900">
                {activeHotel.selected_passenger_count}
              </strong>{" "}
              hotel passenger{activeHotel.selected_passenger_count === 1 ? "" : "s"} |{" "}
              <strong className="font-semibold text-amber-800">
                {activeHotel.selected_passengers.filter((passenger) => passenger.is_vip).length}
              </strong>{" "}
              VIP
            </div>
            <Button
              type="button"
              onClick={() => void runAllocation()}
              isLoading={isAllocating}
              disabled={!canAllocate}
              size="lg"
            >
              <Sparkles className="h-4 w-4" aria-hidden="true" />
              Auto-allocate rooms
            </Button>
          </div>
        </CardContent>
      </Card>

      <GeneratedRoomPlan
        hotel={activeHotel}
        isExporting={isExporting}
        onExport={onExport}
      />
    </div>
  );
}

function GeneratedRoomPlan({
  hotel,
  isExporting,
  onExport,
}: {
  hotel: RoomingHotel;
  isExporting: boolean;
  onExport: () => Promise<void>;
}) {
  const rooms = useMemo(
    () => [...hotel.rooms].sort(
      (left, right) => (
        left.sort_order - right.sort_order
        || left.room_number.localeCompare(right.room_number, undefined, {
          numeric: true,
        })
      ),
    ),
    [hotel.rooms],
  );

  return (
    <Card>
      <CardContent className="p-0">
        <div className="flex flex-col gap-2 border-b border-slate-200 px-4 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div>
            <h2 className="font-semibold text-slate-950">
              3. Auto-generated room plan
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              VIP passengers stay alone. Non-VIPs are paired in same-gender
              twin rooms whenever possible; an odd same-gender remainder stays
              alone in a twin room with one spare bed.
            </p>
          </div>
          <Button
            type="button"
            variant="secondary"
            onClick={() => void onExport()}
            isLoading={isExporting}
            disabled={
              rooms.length === 0
              || !hotel.allocation_is_current
            }
            title={
              rooms.length === 0 || !hotel.allocation_is_current
                ? "Run auto allocation again before exporting"
                : "Export this hotel's rooming list"
            }
          >
            <Download className="h-4 w-4" aria-hidden="true" />
            Export Excel
          </Button>
        </div>

        {rooms.length > 0 && !hotel.allocation_is_current && (
          <div
            role="status"
            className="border-b border-amber-200 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-900 sm:px-6"
          >
            Hotel passengers or VIP status changed. This room plan is kept for
            reference only; run auto allocation again before export or check-in.
          </div>
        )}

        {rooms.length === 0 ? (
          <div className="px-5 py-14 text-center">
            <BedDouble
              className="mx-auto h-10 w-10 text-slate-300"
              aria-hidden="true"
            />
            <h3 className="mt-3 font-semibold text-slate-900">
              No auto-allocated rooms yet
            </h3>
            <p className="mx-auto mt-1 max-w-lg text-sm leading-6 text-slate-500">
              Assign this hotel&apos;s passengers, mark VIPs, choose any
              priorities, then run auto allocation.
            </p>
          </div>
        ) : (
          <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3 sm:p-5">
            {rooms.map((room) => (
              <ReadOnlyRoomCard key={room.id} room={room} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

const ReadOnlyRoomCard = memo(function ReadOnlyRoomCard({ room }: { room: RoomingRoom }) {
  const vip = (
    room.allocation_tag === "vip"
    || room.occupants.some((passenger) => passenger.is_vip)
  );
  const gender = room.occupants.length > 0
    ? normalizeRoomingGender(
      room.occupants[0].passport_sex,
    )
    : null;

  return (
    <article
      className={`overflow-hidden rounded-xl border [contain-intrinsic-size:180px] [content-visibility:auto] ${
        vip
          ? "border-amber-300 bg-amber-50/70"
          : "border-slate-200 bg-white"
      }`}
    >
      <div className="flex items-start justify-between gap-3 border-b border-inherit px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            {vip && (
              <Crown
                className="h-4 w-4 text-amber-700"
                aria-hidden="true"
              />
            )}
            <h3 className="font-semibold text-slate-950">
              Room {room.room_number}
            </h3>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {vip
              ? "VIP single"
              : room.occupants.length === 1
                ? "Twin room with spare bed"
                : "Two-person twin"} |{" "}
            {room.occupants.length}/{room.capacity}
          </p>
        </div>
        {gender && <Badge variant="outline">{gender}</Badge>}
      </div>
      <ul className="divide-y divide-slate-100 px-4">
        {room.occupants.map((passenger) => (
          <li
            key={passenger.passenger_id}
            className="flex items-center justify-between gap-2 py-3 text-sm"
          >
            <span className="font-medium text-slate-900">
              {passenger.client_name}
            </span>
            {passenger.is_vip && (
              <span className="text-xs font-bold text-amber-800">VIP</span>
            )}
          </li>
        ))}
      </ul>
    </article>
  );
});

function createPrioritySlots(
  fields: RoomingPriorityField[],
): Array<string | null> {
  return Array.from(
    { length: MAX_PRIORITY_SLOTS },
    (_, index) => fields[index]?.key ?? null,
  );
}

function compactPrioritySlots(
  slots: Array<string | null>,
): Array<string | null> {
  const selected = slots.filter((key): key is string => Boolean(key));
  return Array.from(
    { length: MAX_PRIORITY_SLOTS },
    (_, index) => selected[index] ?? null,
  );
}

function prioritySourceLabel(source: string) {
  const normalized = source.trim().toLocaleLowerCase();
  if (normalized === "whatsapp") return "WhatsApp spreadsheet";
  if (normalized === "contact") return "Contact field";
  if (normalized === "group_field") return "Group extra field";
  if (normalized === "custom_question") return "Group extra field";
  if (normalized === "custom_detail") return "Group extra field";
  if (normalized === "passport") return "Passport field";
  if (normalized === "submission") return "Traveller/group field";
  return source || "Saved group field";
}

function sanitizePrioritySlots(
  slots: Array<string | null>,
  allowedByKey: Map<string, RoomingPriorityField>,
) {
  return compactPrioritySlots(
    slots.filter(
      (key): key is string => Boolean(key) && allowedByKey.has(key as string),
    ),
  );
}
