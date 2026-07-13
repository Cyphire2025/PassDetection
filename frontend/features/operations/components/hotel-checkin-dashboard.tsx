"use client";

import { useMemo, useState } from "react";
import { Download, KeyRound, MessageSquarePlus, PackageCheck, Save } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, CardContent } from "@/components/ui";
import { operationsApi, type HotelCheckinDashboard as HotelCheckinDashboardData, type HotelCheckinPassenger } from "../api/operations.api";

const EMPTY_CHECKIN_ID = "00000000-0000-0000-0000-000000000000";
const queryKey = (hotelId: string) => ["rooming", "checkins", hotelId];

export function HotelCheckinDashboard({ hotelId }: { hotelId: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: queryKey(hotelId), queryFn: () => operationsApi.hotelCheckins(hotelId) });
  const [filter, setFilter] = useState("all");
  const [editingRemarkFor, setEditingRemarkFor] = useState<string | null>(null);
  const [remarkDraft, setRemarkDraft] = useState("");

  const updateMutation = useMutation({
    mutationFn: ({ checkinId, body }: { checkinId: string; body: { key_issued?: boolean; welcome_letter_issued?: boolean; remarks?: string } }) =>
      operationsApi.updateHotelCheckin(checkinId, body),
    onSuccess: (updated) => {
      queryClient.setQueryData<HotelCheckinDashboardData>(queryKey(hotelId), (current) => current ? applyUpdatedPassenger(current, updated) : current);
      setEditingRemarkFor(null);
    },
  });

  const rows = useMemo(() => (data?.passengers ?? []).filter((row) => {
    if (filter === "not_checked_in") return !row.checked_in;
    if (filter === "key_pending") return !row.key_issued;
    if (filter === "kit_pending") return !row.welcome_letter_issued;
    if (filter === "missing") return row.room_has_missing_occupants;
    if (filter === "vip") return row.is_vip || row.has_special_request;
    if (filter === "checked_in") return row.checked_in;
    return true;
  }), [data, filter]);

  const exportSheet = async () => {
    const blob = await operationsApi.exportHotelCheckins(hotelId);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "hotel_checkins.xlsx";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const startRemarkEdit = (row: HotelCheckinPassenger) => {
    setEditingRemarkFor(row.passenger_id);
    setRemarkDraft(row.remarks ?? "");
  };

  if (isLoading) return <div className="rounded-lg border p-8 text-sm text-slate-500">Loading hotel check-in control...</div>;
  if (!data) return <div className="rounded-lg border border-red-200 p-5 text-sm text-red-700">Hotel check-in dashboard could not be loaded.</div>;

  const stats = [
    ["Allocated", data.total_allocated_passengers],
    ["Checked in", data.checked_in_count],
    ["Keys", data.keys_issued_count],
    ["Welcome kits", data.welcome_letters_issued_count],
    ["Rooms complete", data.rooms_complete],
    ["Rooms missing", data.rooms_with_missing_occupants],
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold text-slate-900">Hotel Check-in</h2>
          <p className="text-sm text-slate-500">Live desk control for {data.hotel_name}</p>
        </div>
        <Button variant="secondary" onClick={() => void exportSheet()}>
          <Download className="h-4 w-4" /> Export check-in sheet
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {stats.map(([label, value]) => (
          <Card key={String(label)}>
            <CardContent className="p-3">
              <p className="text-xs text-slate-500">{label}</p>
              <p className="text-xl font-bold text-slate-900">{value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        {[
          ["all", "All"],
          ["not_checked_in", "Not checked in"],
          ["key_pending", "Key pending"],
          ["kit_pending", "Welcome kit pending"],
          ["missing", "Missing occupants"],
          ["vip", "VIP / special"],
          ["checked_in", "Already checked in"],
        ].map(([value, label]) => (
          <button key={value} onClick={() => setFilter(value)} className={`rounded-full px-3 py-1.5 text-xs font-medium ${filter === value ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-700"}`}>
            {label}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500">
            <tr>
              {["Passenger", "Room", "Checked in", "Key", "Welcome kit", "Remarks", "Actions"].map((heading) => (
                <th key={heading} className="px-3 py-3 font-medium">{heading}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const hasCheckinRecord = row.checkin_id !== EMPTY_CHECKIN_ID;
              const isSavingRow = updateMutation.isPending && updateMutation.variables?.checkinId === row.checkin_id;
              return (
                <tr key={row.passenger_id} className="border-t align-top">
                  <td className="px-3 py-3 font-medium">
                    {row.passenger_name}
                    {row.family_group_label && <span className="ml-2 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-semibold text-blue-700">{row.family_size === 2 ? "Couple" : "Family"}</span>}
                    {(row.is_vip || row.has_special_request) && <span className="ml-2 text-xs text-amber-700">VIP</span>}
                    {row.family_group_label && <p className="mt-1 text-xs font-normal text-blue-700">{row.family_group_label}{row.family_relation ? ` - ${row.family_relation}` : ""}</p>}
                    {row.room_has_missing_occupants && <p className="mt-1 text-xs font-normal text-amber-700">Room has missing occupants</p>}
                  </td>
                  <td className="px-3 py-3">{row.room_number} - {row.room_type}</td>
                  <td className="px-3 py-3"><BooleanLabel value={row.checked_in} /></td>
                  <td className="px-3 py-3"><BooleanLabel value={row.key_issued} /></td>
                  <td className="px-3 py-3"><BooleanLabel value={row.welcome_letter_issued} /></td>
                  <td className="min-w-64 px-3 py-3 text-slate-600">
                    {editingRemarkFor === row.passenger_id ? (
                      <div className="space-y-2">
                        <textarea
                          className="min-h-16 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                          value={remarkDraft}
                          onChange={(event) => setRemarkDraft(event.target.value)}
                          disabled={!hasCheckinRecord}
                        />
                        <div className="flex gap-2">
                          <Button size="sm" variant="secondary" onClick={() => setEditingRemarkFor(null)}>Cancel</Button>
                          <Button
                            size="sm"
                            isLoading={isSavingRow}
                            disabled={!hasCheckinRecord}
                            onClick={() => updateMutation.mutate({ checkinId: row.checkin_id, body: { remarks: remarkDraft } })}
                          >
                            <Save className="h-4 w-4" /> Save
                          </Button>
                        </div>
                      </div>
                    ) : (
                      row.remarks ?? "-"
                    )}
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex min-w-64 flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={!hasCheckinRecord || row.key_issued}
                        isLoading={isSavingRow}
                        onClick={() => updateMutation.mutate({ checkinId: row.checkin_id, body: { key_issued: true } })}
                      >
                        <KeyRound className="h-4 w-4" /> Key
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={!hasCheckinRecord || row.welcome_letter_issued}
                        isLoading={isSavingRow}
                        onClick={() => updateMutation.mutate({ checkinId: row.checkin_id, body: { welcome_letter_issued: true } })}
                      >
                        <PackageCheck className="h-4 w-4" /> Welcome
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={!hasCheckinRecord}
                        onClick={() => startRemarkEdit(row)}
                      >
                        <MessageSquarePlus className="h-4 w-4" /> Remark
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BooleanLabel({ value }: { value: boolean }) {
  return <span className={value ? "font-semibold text-emerald-700" : "text-slate-500"}>{value ? "Yes" : "No"}</span>;
}

function applyUpdatedPassenger(data: HotelCheckinDashboardData, updated: HotelCheckinPassenger): HotelCheckinDashboardData {
  const passengers = data.passengers.map((passenger) => passenger.passenger_id === updated.passenger_id ? updated : passenger);
  return {
    ...data,
    checked_in_count: passengers.filter((passenger) => passenger.checked_in).length,
    keys_issued_count: passengers.filter((passenger) => passenger.key_issued).length,
    welcome_letters_issued_count: passengers.filter((passenger) => passenger.welcome_letter_issued).length,
    passengers,
  };
}
