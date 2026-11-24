"use client";

import type { ReactNode } from "react";
import { BedDouble, Crown, Edit3, Hotel, UsersRound } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import type { RoomingHotel } from "../api/operations.api";

export function HotelSummary({
  hotel,
  passengerTotal,
  onEdit,
}: {
  hotel: RoomingHotel;
  passengerTotal: number;
  onEdit: () => void;
}) {
  const vipCount = hotel.selected_passengers.filter(
    (passenger) => passenger.is_vip,
  ).length;
  const placementPercent = passengerTotal === 0
    ? 0
    : Math.min(100, Math.round((hotel.selected_passenger_count / passengerTotal) * 100));

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm" aria-labelledby="active-hotel-heading">
      <div className="flex flex-col gap-4 p-4 sm:p-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-700 ring-1 ring-blue-100">
            <Hotel className="h-5 w-5" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h2 id="active-hotel-heading" className="truncate font-semibold text-slate-950">
              {hotel.hotel_name}
            </h2>
            <p className="mt-0.5 text-sm text-slate-500">
              {[
                hotel.city,
                hotel.check_in_date && hotel.check_out_date
                  ? `${hotel.check_in_date} to ${hotel.check_out_date}`
                  : null,
              ].filter(Boolean).join(" | ") || "Hotel stay details not set"}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatPill
            icon={<UsersRound className="h-4 w-4" />}
            label="hotel passengers"
            value={`${hotel.selected_passenger_count}/${passengerTotal}`}
          />
          <StatPill
            icon={<Crown className="h-4 w-4" />}
            label="VIP"
            value={vipCount}
          />
          <StatPill
            icon={<BedDouble className="h-4 w-4" />}
            label="auto rooms"
            value={hotel.rooms.length}
          />
          {hotel.allocation_is_current && hotel.allocation_revision > 0 ? (
            <Badge variant="success">
              Current - revision {hotel.allocation_revision}
            </Badge>
          ) : hotel.selected_passenger_count > 0 ? (
            <Badge variant="warning">Needs auto-allocation</Badge>
          ) : null}
          <Button type="button" variant="secondary" onClick={onEdit}>
            <Edit3 className="h-4 w-4" aria-hidden="true" />
            Edit hotel
          </Button>
        </div>
      </div>
      <div className="flex items-center gap-3 border-t border-slate-100 bg-slate-50/70 px-4 py-2.5 sm:px-5">
        <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-slate-200" aria-hidden="true">
          <div className="h-full rounded-full bg-blue-600 transition-[width]" style={{ width: `${placementPercent}%` }} />
        </div>
        <span className="shrink-0 text-xs font-semibold tabular-nums text-slate-600">
          {placementPercent}% of group placed here
        </span>
      </div>
    </section>
  );
}

function StatPill({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string | number;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600">
      <span className="text-slate-400" aria-hidden="true">{icon}</span>
      <span className="text-slate-900">{value}</span>
      <span>{label}</span>
    </span>
  );
}
