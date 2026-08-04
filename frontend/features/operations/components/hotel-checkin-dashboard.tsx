"use client";

import { useDeferredValue, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Download,
  KeyRound,
  MessageSquarePlus,
  PackageCheck,
  Search,
  Save,
  UsersRound,
  X,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Skeleton } from "@/components/ui";
import { cn } from "@/lib/utils/cn";
import { operationsApi, type HotelCheckinDashboard as HotelCheckinDashboardData, type HotelCheckinPassenger } from "../api/operations.api";
import { OperationsErrorNotice, OperationsSummaryItem, OperationsSummaryStrip } from "./operations-workspace-ui";

const EMPTY_CHECKIN_ID = "00000000-0000-0000-0000-000000000000";
const queryKey = (hotelId: string) => ["rooming", "checkins", hotelId];

type CheckinFilter = "all" | "not_checked_in" | "key_pending" | "kit_pending" | "missing" | "vip" | "checked_in";

export function HotelCheckinDashboard({ hotelId }: { hotelId: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: queryKey(hotelId),
    queryFn: () => operationsApi.hotelCheckins(hotelId),
    retry: false,
  });
  const [filter, setFilter] = useState<CheckinFilter>("all");
  const [query, setQuery] = useState("");
  const [editingRemarkFor, setEditingRemarkFor] = useState<string | null>(null);
  const [remarkDraft, setRemarkDraft] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const deferredQuery = useDeferredValue(query);

  const updateMutation = useMutation({
    mutationFn: ({ checkinId, body }: { checkinId: string; body: { key_issued?: boolean; welcome_letter_issued?: boolean; remarks?: string } }) =>
      operationsApi.updateHotelCheckin(checkinId, body),
    onSuccess: (updated) => {
      queryClient.setQueryData<HotelCheckinDashboardData>(queryKey(hotelId), (current) => current ? applyUpdatedPassenger(current, updated) : current);
      setEditingRemarkFor(null);
    },
  });

  const rows = useMemo(() => {
    const normalized = deferredQuery.trim().toLocaleLowerCase();
    return (data?.passengers ?? []).filter((row) => {
      if (filter === "not_checked_in" && row.checked_in) return false;
      if (filter === "key_pending" && row.key_issued) return false;
      if (filter === "kit_pending" && row.welcome_letter_issued) return false;
      if (filter === "missing" && !row.room_has_missing_occupants) return false;
      if (filter === "vip" && !row.is_vip && !row.has_special_request) return false;
      if (filter === "checked_in" && !row.checked_in) return false;
      if (!normalized) return true;
      return [row.passenger_name, row.room_number, row.family_group_label, row.family_relation, row.remarks]
        .some((value) => value?.toLocaleLowerCase().includes(normalized));
    });
  }, [data?.passengers, deferredQuery, filter]);

  const exportSheet = async () => {
    if (exporting) return;
    setExportError(null);
    setExporting(true);
    try {
      const blob = await operationsApi.exportHotelCheckins(hotelId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "hotel_checkins.xlsx";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch {
      setExportError("The hotel check-in sheet could not be exported. Please try again.");
    } finally {
      setExporting(false);
    }
  };

  const startRemarkEdit = (row: HotelCheckinPassenger) => {
    setEditingRemarkFor(row.passenger_id);
    setRemarkDraft(row.remarks ?? "");
  };

  if (isLoading) {
    return (
      <div className="space-y-4" role="status" aria-label="Loading hotel check-in control">
        <Skeleton className="h-16 rounded-xl" />
        <Skeleton className="h-[72px] rounded-xl" />
        <Skeleton className="h-80 rounded-xl" />
      </div>
    );
  }
  if (error || !data) {
    return <OperationsErrorNotice>Hotel check-in control could not be loaded. The room plan remains available in the Allocation tab.</OperationsErrorNotice>;
  }

  const filters: Array<[CheckinFilter, string, number]> = [
    ["all", "All", data.passengers.length],
    ["not_checked_in", "Not checked in", data.passengers.filter((row) => !row.checked_in).length],
    ["key_pending", "Key pending", data.passengers.filter((row) => !row.key_issued).length],
    ["kit_pending", "Welcome kit pending", data.passengers.filter((row) => !row.welcome_letter_issued).length],
    ["missing", "Missing occupants", data.passengers.filter((row) => row.room_has_missing_occupants).length],
    ["vip", "VIP / special", data.passengers.filter((row) => row.is_vip || row.has_special_request).length],
    ["checked_in", "Checked in", data.checked_in_count],
  ];
  const completionPercent = data.total_allocated_passengers === 0
    ? 0
    : Math.round((data.checked_in_count / data.total_allocated_passengers) * 100);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white px-4 py-4 shadow-sm sm:px-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold text-slate-950">Hotel check-in desk</h2>
            <Badge variant="secondary" dot>Live control</Badge>
          </div>
          <p className="mt-1 text-sm text-slate-500">Track arrivals, keys, welcome kits, and room-level exceptions for {data.hotel_name}.</p>
        </div>
        <Button variant="secondary" onClick={() => void exportSheet()} isLoading={exporting}>
          <Download className="h-4 w-4" aria-hidden="true" /> Export check-in sheet
        </Button>
      </div>

      {(exportError || updateMutation.error) && (
        <OperationsErrorNotice>{exportError ?? "The check-in update could not be saved. The previous value remains active."}</OperationsErrorNotice>
      )}

      <OperationsSummaryStrip label="Hotel check-in summary">
        <OperationsSummaryItem label="Allocated" value={data.total_allocated_passengers} helper="passengers" icon={UsersRound} />
        <OperationsSummaryItem label="Checked in" value={data.checked_in_count} helper={`${completionPercent}% complete`} icon={CheckCircle2} tone={completionPercent === 100 && data.total_allocated_passengers > 0 ? "success" : "default"} />
        <OperationsSummaryItem label="Keys issued" value={data.keys_issued_count} helper={`${Math.max(0, data.total_allocated_passengers - data.keys_issued_count)} pending`} icon={KeyRound} />
        <OperationsSummaryItem label="Rooms missing" value={data.rooms_with_missing_occupants} helper={`${data.rooms_complete} complete`} icon={AlertTriangle} tone={data.rooms_with_missing_occupants > 0 ? "attention" : "success"} />
      </OperationsSummaryStrip>

      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm" aria-labelledby="checkin-roster-heading">
        <div className="border-b border-slate-200 bg-slate-50/70 px-4 py-3.5 sm:px-5">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <div className="min-w-0">
              <h3 id="checkin-roster-heading" className="text-sm font-semibold text-slate-950">Passenger desk roster</h3>
              <p className="mt-0.5 text-xs text-slate-500" aria-live="polite">{rows.length} of {data.passengers.length} passengers visible</p>
            </div>
            <div className="relative min-w-0 flex-1 xl:max-w-sm">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search passenger, room, family, or remark"
                aria-label="Search hotel check-in roster"
                className="h-9 w-full rounded-lg border border-slate-300 bg-white pl-9 pr-8 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
              {query && (
                <button type="button" onClick={() => setQuery("")} aria-label="Clear check-in search" className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
                  <X className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              )}
            </div>
          </div>
          <div className="mt-3 flex gap-2 overflow-x-auto pb-1" aria-label="Filter check-in roster">
            {filters.map(([value, label, count]) => (
              <button
                key={value}
                type="button"
                onClick={() => setFilter(value)}
                aria-pressed={filter === value}
                className={cn(
                  "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors",
                  filter === value ? "border-blue-700 bg-blue-700 text-white" : "border-slate-200 bg-white text-slate-600 hover:border-blue-200 hover:bg-blue-50",
                )}
              >
                {label}<span className={cn("tabular-nums", filter === value ? "text-blue-100" : "text-slate-400")}>{count}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="max-h-[64vh] overflow-auto">
          <table className="w-full min-w-[1040px] text-left text-sm">
            <caption className="sr-only">Hotel check-in passenger control for {data.hotel_name}</caption>
            <thead className="sticky top-0 z-10 border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500 shadow-[0_1px_0_rgba(226,232,240,1)]">
              <tr>
                {["Passenger", "Room", "Checked in", "Key", "Welcome kit", "Remarks", "Actions"].map((heading) => (
                  <th key={heading} scope="col" className="px-3 py-3">{heading}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((row) => {
                const hasCheckinRecord = row.checkin_id !== EMPTY_CHECKIN_ID;
                const isSavingRow = updateMutation.isPending && updateMutation.variables?.checkinId === row.checkin_id;
                return (
                  <tr key={row.passenger_id} className="align-top transition-colors hover:bg-slate-50/80 [contain-intrinsic-size:64px] [content-visibility:auto]">
                    <td className="px-3 py-3 font-medium">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-slate-950">{row.passenger_name}</span>
                        {row.family_group_label && <Badge variant="secondary">{row.family_size === 2 ? "Couple" : "Family"}</Badge>}
                        {(row.is_vip || row.has_special_request) && <Badge variant="warning">VIP / special</Badge>}
                      </div>
                      {row.family_group_label && <p className="mt-1 text-xs font-normal text-blue-700">{row.family_group_label}{row.family_relation ? ` - ${row.family_relation}` : ""}</p>}
                      {row.room_has_missing_occupants && <p className="mt-1 text-xs font-semibold text-amber-700">Room has missing occupants</p>}
                    </td>
                    <td className="px-3 py-3 font-medium text-slate-700">{row.room_number}<span className="ml-1 text-xs font-normal text-slate-400">{row.room_type}</span></td>
                    <td className="px-3 py-3"><BooleanLabel value={row.checked_in} /></td>
                    <td className="px-3 py-3"><BooleanLabel value={row.key_issued} /></td>
                    <td className="px-3 py-3"><BooleanLabel value={row.welcome_letter_issued} /></td>
                    <td className="min-w-64 px-3 py-3 text-slate-600">
                      {editingRemarkFor === row.passenger_id ? (
                        <div className="space-y-2">
                          <label className="sr-only" htmlFor={`checkin-remark-${row.passenger_id}`}>Remark for {row.passenger_name}</label>
                          <textarea
                            id={`checkin-remark-${row.passenger_id}`}
                            className="min-h-16 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                            value={remarkDraft}
                            onChange={(event) => setRemarkDraft(event.target.value)}
                            disabled={!hasCheckinRecord}
                          />
                          <div className="flex gap-2">
                            <Button size="sm" variant="secondary" onClick={() => setEditingRemarkFor(null)}>Cancel</Button>
                            <Button size="sm" isLoading={isSavingRow} disabled={!hasCheckinRecord} onClick={() => updateMutation.mutate({ checkinId: row.checkin_id, body: { remarks: remarkDraft } })}>
                              <Save className="h-4 w-4" aria-hidden="true" /> Save
                            </Button>
                          </div>
                        </div>
                      ) : (row.remarks ?? <span className="text-slate-400">No remark</span>)}
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex min-w-64 flex-wrap gap-2">
                        <Button size="sm" variant="secondary" disabled={!hasCheckinRecord || row.key_issued} isLoading={isSavingRow} onClick={() => updateMutation.mutate({ checkinId: row.checkin_id, body: { key_issued: true } })}>
                          <KeyRound className="h-4 w-4" aria-hidden="true" /> Issue key
                        </Button>
                        <Button size="sm" variant="secondary" disabled={!hasCheckinRecord || row.welcome_letter_issued} isLoading={isSavingRow} onClick={() => updateMutation.mutate({ checkinId: row.checkin_id, body: { welcome_letter_issued: true } })}>
                          <PackageCheck className="h-4 w-4" aria-hidden="true" /> Welcome kit
                        </Button>
                        <Button size="sm" variant="ghost" disabled={!hasCheckinRecord} onClick={() => startRemarkEdit(row)}>
                          <MessageSquarePlus className="h-4 w-4" aria-hidden="true" /> Remark
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 && (
            <div className="px-5 py-12 text-center">
              <Search className="mx-auto h-6 w-6 text-slate-300" aria-hidden="true" />
              <p className="mt-3 text-sm font-semibold text-slate-800">No passengers match this desk view</p>
              <button type="button" onClick={() => { setQuery(""); setFilter("all"); }} className="mt-2 text-sm font-semibold text-blue-700 hover:text-blue-900">Reset filters</button>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function BooleanLabel({ value }: { value: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-semibold", value ? "text-emerald-700" : "text-slate-500")}>
      {value ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : <span className="h-1.5 w-1.5 rounded-full bg-slate-300" aria-hidden="true" />}
      {value ? "Complete" : "Pending"}
    </span>
  );
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
