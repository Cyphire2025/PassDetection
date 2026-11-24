"use client";

import { memo, useState } from "react";
import { Crown, UserCheck } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import type { RoomingPassenger } from "../api/operations.api";

export function PassengerTable({
  caption,
  passengers,
  activeHotelId,
  selected,
  disabled,
  onTogglePassenger,
}: {
  caption: string;
  passengers: RoomingPassenger[];
  activeHotelId: string;
  selected: Set<string>;
  disabled: boolean;
  onTogglePassenger: (passengerId: string) => void;
}) {
  const [page, setPage] = useState(1);
  const pageSize = 50;
  const pageCount = Math.max(1, Math.ceil(passengers.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const pagePassengers = passengers.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize,
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] border-collapse text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="w-12 px-4 py-3">
              <span className="sr-only">Select passenger</span>
            </th>
            <th scope="col" className="px-3 py-3">
              Passenger
            </th>
            <th scope="col" className="px-3 py-3">
              Gender
            </th>
            <th scope="col" className="px-3 py-3">
              Current hotel
            </th>
            <th scope="col" className="px-4 py-3">
              Room rule
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {pagePassengers.map((passenger) => (
            <PassengerRow
              key={passenger.passenger_id}
              passenger={passenger}
              activeHotelId={activeHotelId}
              checked={selected.has(passenger.passenger_id)}
              disabled={disabled}
              onTogglePassenger={onTogglePassenger}
            />
          ))}
        </tbody>
      </table>
      {pageCount > 1 && (
        <div className="flex items-center justify-between gap-3 border-t border-slate-200 px-4 py-3">
          <p className="text-xs text-slate-500">
            Page {currentPage} of {pageCount} | {passengers.length} passengers |
            selections stay selected across pages
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={currentPage <= 1}
              onClick={() => setPage(currentPage - 1)}
            >
              Previous
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={currentPage >= pageCount}
              onClick={() => setPage(currentPage + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

const PassengerRow = memo(function PassengerRow({
  passenger,
  activeHotelId,
  checked,
  disabled,
  onTogglePassenger,
}: {
  passenger: RoomingPassenger;
  activeHotelId: string;
  checked: boolean;
  disabled: boolean;
  onTogglePassenger: (passengerId: string) => void;
}) {
  const gender = normalizeRoomingGender(passenger.passport_sex);
  const isAtActiveHotel = passenger.selected_hotel_id === activeHotelId;

  return (
    <tr
      className={
        passenger.is_vip
          ? "bg-amber-50/70 hover:bg-amber-50"
          : checked
            ? "bg-blue-50/60 hover:bg-blue-50"
            : "hover:bg-slate-50/80"
      }
    >
      <td className="px-4 py-3 align-top">
        <input
          type="checkbox"
          checked={checked}
          onChange={() => onTogglePassenger(passenger.passenger_id)}
          disabled={disabled}
          aria-label={`Select ${passenger.client_name}`}
          className="mt-1 h-4 w-4 rounded border-slate-300 accent-blue-600"
        />
      </td>
      <td className="px-3 py-3 align-top">
        <div className="font-semibold text-slate-900">
          {passenger.client_name}
        </div>
        <div className="mt-1 flex flex-wrap gap-1.5 text-xs text-slate-500">
          {passenger.family_group_label && (
            <span>{passenger.family_group_label}</span>
          )}
          {passenger.client_phone && <span>{passenger.client_phone}</span>}
        </div>
      </td>
      <td className="px-3 py-3 align-top">
        {gender ? (
          <Badge variant={gender === "Male" ? "secondary" : "success"}>
            {gender}
          </Badge>
        ) : (
          <Badge variant="destructive">Needs correction</Badge>
        )}
      </td>
      <td className="px-3 py-3 align-top">
        {passenger.selected_hotel_name ? (
          <Badge variant={isAtActiveHotel ? "success" : "outline"}>
            {passenger.selected_hotel_name}
          </Badge>
        ) : (
          <span className="text-slate-400">Not assigned</span>
        )}
      </td>
      <td className="px-4 py-3 align-top">
        {passenger.is_vip ? (
          <span className="inline-flex items-center gap-1.5 font-semibold text-amber-800">
            <Crown className="h-4 w-4" aria-hidden="true" />
            VIP - single room
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-slate-600">
            <UserCheck className="h-4 w-4" aria-hidden="true" />
            Same-gender twin
          </span>
        )}
      </td>
    </tr>
  );
});

export function normalizeRoomingGender(
  value: string | null | undefined,
): "Male" | "Female" | null {
  const normalized = value?.trim().toLocaleLowerCase();
  if (normalized === "m" || normalized === "male") return "Male";
  if (normalized === "f" || normalized === "female") return "Female";
  return null;
}
