"use client";

import { useEffect, useRef } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import type { RoomingPassenger } from "../api/operations.api";
import { PassengerTable } from "./rooming-roster-table";

export function RosterGroupSection({
  contentId,
  label,
  passengerCount,
  selectedCount,
  isMissing,
  expanded,
  passengers,
  activeHotelId,
  selected,
  disabled,
  onToggleExpanded,
  onToggleGroup,
  onTogglePassenger,
}: {
  contentId: string;
  label: string;
  passengerCount: number;
  selectedCount: number;
  isMissing: boolean;
  expanded: boolean;
  passengers: RoomingPassenger[];
  activeHotelId: string;
  selected: Set<string>;
  disabled: boolean;
  onToggleExpanded: () => void;
  onToggleGroup: (shouldSelect: boolean) => void;
  onTogglePassenger: (passengerId: string) => void;
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex items-center gap-3 bg-slate-50 px-4 py-3">
        <GroupSelectionCheckbox
          label={`Select ${label}`}
          selectedCount={selectedCount}
          passengerCount={passengerCount}
          disabled={disabled}
          onChange={onToggleGroup}
        />
        <button
          type="button"
          onClick={onToggleExpanded}
          aria-expanded={expanded}
          aria-controls={contentId}
          className="flex min-w-0 flex-1 items-center justify-between gap-3 text-left"
        >
          <span className="min-w-0">
            <span
              className={
                isMissing
                  ? "font-semibold text-amber-800"
                  : "font-semibold text-slate-900"
              }
            >
              {label}
            </span>
            <span className="ml-2 text-xs text-slate-500">
              {passengerCount} passenger{passengerCount === 1 ? "" : "s"}
              {selectedCount > 0 ? ` | ${selectedCount} selected` : ""}
            </span>
          </span>
          {expanded ? (
            <ChevronUp
              className="h-4 w-4 shrink-0 text-slate-500"
              aria-hidden="true"
            />
          ) : (
            <ChevronDown
              className="h-4 w-4 shrink-0 text-slate-500"
              aria-hidden="true"
            />
          )}
        </button>
        <button
          type="button"
          onClick={() => onToggleGroup(selectedCount !== passengerCount)}
          disabled={disabled || passengerCount === 0}
          className="shrink-0 rounded-md px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50 disabled:opacity-50"
        >
          {selectedCount === passengerCount ? "Clear group" : "Select group"}
        </button>
      </div>
      {expanded && (
        <div
          id={contentId}
          className="overflow-x-auto border-t border-slate-200"
        >
          <PassengerTable
            caption={`${label} passenger roster`}
            passengers={passengers}
            activeHotelId={activeHotelId}
            selected={selected}
            disabled={disabled}
            onTogglePassenger={onTogglePassenger}
          />
        </div>
      )}
    </section>
  );
}

function GroupSelectionCheckbox({
  label,
  selectedCount,
  passengerCount,
  disabled,
  onChange,
}: {
  label: string;
  selectedCount: number;
  passengerCount: number;
  disabled: boolean;
  onChange: (shouldSelect: boolean) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const checked = passengerCount > 0 && selectedCount === passengerCount;
  const indeterminate = selectedCount > 0 && selectedCount < passengerCount;
  useEffect(() => {
    if (inputRef.current) inputRef.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return (
    <input
      ref={inputRef}
      type="checkbox"
      checked={checked}
      onChange={() => onChange(!checked)}
      disabled={disabled || passengerCount === 0}
      aria-label={label}
      aria-checked={indeterminate ? "mixed" : checked}
      className="h-4 w-4 shrink-0 rounded border-slate-300 accent-blue-600"
    />
  );
}
