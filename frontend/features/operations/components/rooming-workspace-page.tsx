"use client";

import { ArrowLeft, CheckCircle2, ClipboardList, Hotel, MapPin, Plus, RefreshCw, UsersRound } from "lucide-react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { Button } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { useRoomingWorkspaceController } from "../hooks/use-rooming-workspace-controller";
import { RoomingAutoAllocation } from "./rooming-auto-allocation";
import { RoomingPassengerHotelAllocation } from "./rooming-passenger-hotel-allocation";
import { HotelSummary } from "./rooming-hotel-summary";
import { CreateHotelDialog, EditHotelDialog } from "./rooming-hotel-dialog";
import { CheckinLoading, EmptyRoomingState, HeaderContext, RoomingLoading } from "./rooming-workspace-states";
import { OperationsErrorNotice, OperationsPageHeader, OperationsSummaryItem, OperationsSummaryStrip } from "./operations-workspace-ui";

const HotelCheckinDashboard = dynamic(
  () => import("./hotel-checkin-dashboard").then((module) => module.HotelCheckinDashboard),
  { loading: () => <CheckinLoading /> },
);

export function RoomingWorkspacePage({ groupId }: { groupId: string }) {
  const { data, isLoading, error, priorityFields, actions, activeHotel, setSelectedHotelId,
    showHotelDialog, setShowHotelDialog, showHotelEditDialog, setShowHotelEditDialog,
    hotelTab, setHotelTab, actionError, setActionError, isExporting, exportHotel,
  } = useRoomingWorkspaceController(groupId);

  if (isLoading) return <RoomingLoading />;
  if (error || !data) {
    return (
      <OperationsErrorNotice>
        Rooming workspace could not be loaded. Refresh the page and try again.
      </OperationsErrorNotice>
    );
  }

  const assignedPassengerCount = data.passengers.filter(
    (passenger) => Boolean(passenger.selected_hotel_id),
  ).length;
  const unassignedPassengerCount = Math.max(0, data.total_passengers - assignedPassengerCount);

  return (
    <div className="flex flex-col gap-5">
      <OperationsPageHeader
        title={data.group_name}
        description="Assign passengers to hotels, allocate rooms, and manage check-in."
        icon={Hotel}
        context={(
          <>
            {data.destination && <HeaderContext icon={MapPin}>{data.destination}</HeaderContext>}
            <HeaderContext icon={UsersRound}>{data.total_passengers.toLocaleString()} passengers</HeaderContext>
            <HeaderContext icon={Hotel}>{data.hotels.length} hotel{data.hotels.length === 1 ? "" : "s"}</HeaderContext>
          </>
        )}
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={ROUTES.dashboard.rooming}
              className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-3.5 text-sm font-semibold text-white transition hover:bg-white/15"
            >
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
              All rooming lists
            </Link>
            <Button
              type="button"
              onClick={() => setShowHotelDialog(true)}
              className="bg-white text-blue-950 hover:bg-sky-50 active:bg-sky-100"
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              Add hotel
            </Button>
          </div>
        )}
      />

      <OperationsSummaryStrip label={`${data.group_name} rooming readiness`}>
        <OperationsSummaryItem label="Group roster" value={data.total_passengers.toLocaleString()} helper="passengers" icon={UsersRound} />
        <OperationsSummaryItem label="Hotel stays" value={data.hotels.length} helper="configured" icon={Hotel} />
        <OperationsSummaryItem label="Placed" value={assignedPassengerCount.toLocaleString()} helper="in a hotel" icon={CheckCircle2} tone={assignedPassengerCount === data.total_passengers && data.total_passengers > 0 ? "success" : "default"} />
        <OperationsSummaryItem label="Unassigned" value={unassignedPassengerCount.toLocaleString()} helper="need placement" icon={ClipboardList} tone={unassignedPassengerCount > 0 ? "attention" : "success"} />
      </OperationsSummaryStrip>

      {actionError && (
        <OperationsErrorNotice>{actionError}</OperationsErrorNotice>
      )}

      {data.hotels.length === 0 ? (
        <EmptyRoomingState
          passengerCount={data.total_passengers}
          onCreate={() => setShowHotelDialog(true)}
        />
      ) : (
        <>
          <nav
            aria-label="Rooming hotels"
            className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-2 shadow-sm"
          >
            <div className="flex min-w-max items-center gap-2">
              {data.hotels.map((hotel) => (
                <button
                  key={hotel.id}
                  type="button"
                  onClick={() => {
                    setSelectedHotelId(hotel.id);
                    setHotelTab("allocation");
                    setActionError(null);
                  }}
                  aria-current={hotel.id === activeHotel?.id ? "page" : undefined}
                  className={`group inline-flex items-center gap-2 rounded-lg border px-3.5 py-2.5 text-sm font-semibold transition-colors ${
                    hotel.id === activeHotel?.id
                      ? "border-blue-700 bg-blue-700 text-white shadow-sm"
                      : "border-transparent bg-slate-50 text-slate-700 hover:border-blue-200 hover:bg-blue-50"
                  }`}
                >
                  <span className={`h-2 w-2 rounded-full ${hotel.allocation_is_current ? "bg-emerald-400" : hotel.selected_passenger_count > 0 ? "bg-amber-400" : "bg-slate-300"}`} aria-hidden="true" />
                  {hotel.hotel_name}
                  <span
                    className={`ml-2 rounded-full px-2 py-0.5 text-xs ${
                      hotel.id === activeHotel?.id
                        ? "bg-white/15 text-white"
                        : "bg-white text-slate-600 ring-1 ring-slate-200"
                    }`}
                  >
                    {hotel.selected_passenger_count}
                  </span>
                </button>
              ))}
            </div>
          </nav>

          {activeHotel && (
            <>
              <HotelSummary
                hotel={activeHotel}
                passengerTotal={data.total_passengers}
                onEdit={() => setShowHotelEditDialog(true)}
              />

              <div
                role="tablist"
                aria-label={`${activeHotel.hotel_name} rooming sections`}
                className="inline-flex w-fit rounded-lg border border-slate-200 bg-slate-100 p-1"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={hotelTab === "allocation"}
                  onClick={() => setHotelTab("allocation")}
                  className={`rounded-md px-3.5 py-2 text-sm font-semibold transition-colors ${
                    hotelTab === "allocation"
                      ? "bg-white text-blue-800 shadow-sm"
                      : "text-slate-600 hover:bg-white/60 hover:text-slate-900"
                  }`}
                >
                  Allocation
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={hotelTab === "checkins"}
                  onClick={() => setHotelTab("checkins")}
                  className={`rounded-md px-3.5 py-2 text-sm font-semibold transition-colors ${
                    hotelTab === "checkins"
                      ? "bg-white text-blue-800 shadow-sm"
                      : "text-slate-600 hover:bg-white/60 hover:text-slate-900"
                  }`}
                >
                  Hotel check-in
                </button>
              </div>

              {hotelTab === "checkins" ? (
                activeHotel.rooms.length > 0
                && activeHotel.allocation_is_current ? (
                  <HotelCheckinDashboard hotelId={activeHotel.id} />
                ) : (
                  <div className="rounded-xl border border-amber-200 bg-amber-50 px-5 py-8 text-center">
                    <RefreshCw className="mx-auto h-6 w-6 text-amber-700" aria-hidden="true" />
                    <h2 className="mt-3 font-semibold text-amber-950">Check-in needs a current room plan</h2>
                    <p className="mx-auto mt-1 max-w-xl text-sm leading-6 text-amber-800">
                      Run auto allocation again before opening hotel check-in. Hotel membership or VIP status may have changed since the previous plan.
                    </p>
                  </div>
                )
              ) : (
                <div className="space-y-5">
                  <RoomingPassengerHotelAllocation
                    key={activeHotel.id}
                    workspace={data}
                    activeHotel={activeHotel}
                    isAssigning={actions.selectHotelPassengers.isPending}
                    isUpdatingVip={actions.setPassengerVip.isPending}
                    groupingFields={priorityFields.data?.fields ?? []}
                    groupingFieldsLoading={priorityFields.isLoading}
                    groupingFieldsError={Boolean(priorityFields.error)}
                    onAssign={async (passengerIds, hotelId) => {
                      await actions.selectHotelPassengers.mutateAsync({
                        hotelId,
                        passengerIds,
                        mode: "add",
                      });
                    }}
                    onSetVip={async (passengerIds, isVip) => {
                      await actions.setPassengerVip.mutateAsync({
                        hotelId: activeHotel.id,
                        passengerIds,
                        isVip,
                      });
                    }}
                  />
                  <RoomingAutoAllocation
                    key={`${activeHotel.id}:${activeHotel.allocation_revision}:${activeHotel.allocation_is_current}`}
                    activeHotel={activeHotel}
                    options={priorityFields.data}
                    optionsLoading={priorityFields.isLoading}
                    optionsError={Boolean(priorityFields.error)}
                    isAllocating={actions.autoAllocate.isPending}
                    isExporting={isExporting}
                    onAutoAllocate={async (fields) => {
                      await actions.autoAllocate.mutateAsync({
                        hotelId: activeHotel.id,
                        priorityFields: fields,
                      });
                    }}
                    onExport={exportHotel}
                  />
                </div>
              )}
            </>
          )}
        </>
      )}

      {showHotelDialog && (
        <CreateHotelDialog
          isLoading={actions.createHotel.isPending}
          onClose={() => setShowHotelDialog(false)}
          onCreate={async (body) => {
            const hotel = await actions.createHotel.mutateAsync(body);
            setSelectedHotelId(hotel.id);
            setShowHotelDialog(false);
          }}
        />
      )}
      {showHotelEditDialog && activeHotel && (
        <EditHotelDialog
          hotel={activeHotel}
          isLoading={actions.updateHotel.isPending}
          onClose={() => setShowHotelEditDialog(false)}
          onSave={async (body) => {
            await actions.updateHotel.mutateAsync({
              hotelId: activeHotel.id,
              ...body,
            });
            setShowHotelEditDialog(false);
          }}
        />
      )}
    </div>
  );
}
