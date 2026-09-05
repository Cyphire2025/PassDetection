"use client";

import {
  ArrowLeft,
  BedDouble,
  CheckCircle2,
  ClipboardList,
  Crown,
  Edit3,
  Hotel,
  MapPin,
  Plus,
  RefreshCw,
  UsersRound,
  X,
} from "lucide-react";
import {
  FormEvent,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { Badge, Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { operationsApi, type RoomingHotel } from "../api/operations.api";
import {
  useRoomingActions,
  useRoomingPriorityFields,
  useRoomingWorkspace,
} from "../hooks/use-operations";
import { RoomingAutoAllocation } from "./rooming-auto-allocation";
import { roomingErrorMessage } from "./rooming-error-message";
import { RoomingPassengerHotelAllocation } from "./rooming-passenger-hotel-allocation";
import {
  OperationsErrorNotice,
  OperationsPageHeader,
  OperationsSummaryItem,
  OperationsSummaryStrip,
} from "./operations-workspace-ui";

const HotelCheckinDashboard = dynamic(
  () => import("./hotel-checkin-dashboard").then((module) => module.HotelCheckinDashboard),
  { loading: () => <CheckinLoading /> },
);

type HotelTab = "allocation" | "checkins";

export function RoomingWorkspacePage({ groupId }: { groupId: string }) {
  const { data, isLoading, error } = useRoomingWorkspace(groupId);
  const priorityFields = useRoomingPriorityFields(groupId);
  const actions = useRoomingActions(groupId);
  const [selectedHotelId, setSelectedHotelId] = useState<string | null>(null);
  const [showHotelDialog, setShowHotelDialog] = useState(false);
  const [showHotelEditDialog, setShowHotelEditDialog] = useState(false);
  const [hotelTab, setHotelTab] = useState<HotelTab>("allocation");
  const [actionError, setActionError] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  const activeHotel = (
    data?.hotels.find((hotel) => hotel.id === selectedHotelId)
    ?? data?.hotels[0]
    ?? null
  );

  const exportHotel = async () => {
    if (!activeHotel || activeHotel.rooms.length === 0 || isExporting) return;
    setActionError(null);
    setIsExporting(true);
    try {
      const blob = await operationsApi.exportRoomingHotel(activeHotel.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${
        activeHotel.hotel_name.replace(/[^a-z0-9]+/gi, "_").toLowerCase()
      }_rooming_list.xlsx`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (exportError) {
      setActionError(
        roomingErrorMessage(
          exportError,
          "The hotel rooming workbook could not be generated. Please try again.",
        ),
      );
    } finally {
      setIsExporting(false);
    }
  };

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
              href={ROUTES.dashboard.rooming as never}
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

function HotelSummary({
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

function CreateHotelDialog({
  isLoading,
  onClose,
  onCreate,
}: {
  isLoading: boolean;
  onClose: () => void;
  onCreate: (body: {
    hotel_name: string;
    city?: string;
    check_in_date?: string;
    check_out_date?: string;
  }) => Promise<void>;
}) {
  const [form, setForm] = useState({
    hotel_name: "",
    city: "",
    check_in_date: "",
    check_out_date: "",
  });
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    try {
      await onCreate({
        hotel_name: form.hotel_name.trim(),
        city: form.city.trim() || undefined,
        check_in_date: form.check_in_date || undefined,
        check_out_date: form.check_out_date || undefined,
      });
    } catch (createError) {
      setError(
        roomingErrorMessage(
          createError,
          "Hotel could not be added. Check the stay dates and try again.",
        ),
      );
    }
  };

  return (
    <DialogShell
      title="Add hotel stay"
      icon={<Hotel className="h-5 w-5" aria-hidden="true" />}
      isLoading={isLoading}
      onClose={onClose}
    >
      <form className="space-y-4" onSubmit={submit}>
        <Input
          label="Hotel name"
          placeholder="Marriott Bangkok"
          value={form.hotel_name}
          onChange={(event) => setForm((current) => ({
            ...current,
            hotel_name: event.target.value,
          }))}
          minLength={2}
          maxLength={255}
          required
          autoFocus
        />
        <Input
          label="City"
          placeholder="Bangkok"
          value={form.city}
          onChange={(event) => setForm((current) => ({
            ...current,
            city: event.target.value,
          }))}
          maxLength={120}
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <Input
            label="Check-in"
            type="date"
            value={form.check_in_date}
            onChange={(event) => setForm((current) => ({
              ...current,
              check_in_date: event.target.value,
            }))}
          />
          <Input
            label="Check-out"
            type="date"
            min={form.check_in_date || undefined}
            value={form.check_out_date}
            onChange={(event) => setForm((current) => ({
              ...current,
              check_out_date: event.target.value,
            }))}
          />
        </div>
        {error && (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          >
            {error}
          </div>
        )}
        <DialogActions
          onClose={onClose}
          isLoading={isLoading}
          label="Add hotel"
        />
      </form>
    </DialogShell>
  );
}

function EditHotelDialog({
  hotel,
  isLoading,
  onClose,
  onSave,
}: {
  hotel: RoomingHotel;
  isLoading: boolean;
  onClose: () => void;
  onSave: (body: {
    hotel_name: string;
    city?: string;
    check_in_date?: string;
    check_out_date?: string;
  }) => Promise<void>;
}) {
  const [form, setForm] = useState({
    hotel_name: hotel.hotel_name,
    city: hotel.city ?? "",
    check_in_date: hotel.check_in_date ?? "",
    check_out_date: hotel.check_out_date ?? "",
  });
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    try {
      await onSave({
        hotel_name: form.hotel_name.trim(),
        city: form.city.trim() || undefined,
        check_in_date: form.check_in_date || undefined,
        check_out_date: form.check_out_date || undefined,
      });
    } catch (saveError) {
      setError(
        roomingErrorMessage(
          saveError,
          "Hotel details could not be saved. Check the stay dates and try again.",
        ),
      );
    }
  };

  return (
    <DialogShell
      title={`Edit ${hotel.hotel_name}`}
      icon={<Hotel className="h-5 w-5" aria-hidden="true" />}
      isLoading={isLoading}
      onClose={onClose}
    >
      <form className="space-y-4" onSubmit={submit}>
        <Input
          label="Hotel name"
          value={form.hotel_name}
          onChange={(event) => setForm((current) => ({
            ...current,
            hotel_name: event.target.value,
          }))}
          minLength={2}
          maxLength={255}
          required
          autoFocus
        />
        <Input
          label="City"
          value={form.city}
          onChange={(event) => setForm((current) => ({
            ...current,
            city: event.target.value,
          }))}
          maxLength={120}
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <Input
            label="Check-in"
            type="date"
            value={form.check_in_date}
            onChange={(event) => setForm((current) => ({
              ...current,
              check_in_date: event.target.value,
            }))}
          />
          <Input
            label="Check-out"
            type="date"
            min={form.check_in_date || undefined}
            value={form.check_out_date}
            onChange={(event) => setForm((current) => ({
              ...current,
              check_out_date: event.target.value,
            }))}
          />
        </div>
        {error && (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          >
            {error}
          </div>
        )}
        <DialogActions
          onClose={onClose}
          isLoading={isLoading}
          label="Save hotel"
        />
      </form>
    </DialogShell>
  );
}

function DialogShell({
  title,
  icon,
  isLoading,
  onClose,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  isLoading: boolean;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const onCloseRef = useRef(onClose);
  const loadingRef = useRef(isLoading);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    loadingRef.current = isLoading;
  }, [isLoading]);

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusTimer = window.setTimeout(
      () => closeButtonRef.current?.focus(),
      0,
    );
    const handleKeyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !loadingRef.current) {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((element) => element.offsetParent !== null);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (
        event.shiftKey
        && (
          document.activeElement === first
          || !dialogRef.current?.contains(document.activeElement)
        )
      ) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyboard);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", handleKeyboard);
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus();
    };
  }, []);

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm"
      onMouseDown={(event) => {
        if (
          event.target === event.currentTarget
          && !isLoading
        ) {
          onClose();
        }
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 p-5">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
              {icon}
            </span>
            <h2 id={titleId} className="font-semibold text-slate-900">
              {title}
            </h2>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            disabled={isLoading}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
            aria-label="Close hotel dialog"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

function DialogActions({
  onClose,
  isLoading,
  label,
}: {
  onClose: () => void;
  isLoading: boolean;
  label: string;
}) {
  return (
    <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
      <Button
        type="button"
        variant="secondary"
        onClick={onClose}
        disabled={isLoading}
      >
        Cancel
      </Button>
      <Button type="submit" isLoading={isLoading}>
        {label}
      </Button>
    </div>
  );
}

function StatPill({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
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

function HeaderContext({
  icon: Icon,
  children,
}: {
  icon: typeof Hotel;
  children: React.ReactNode;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-2.5 py-1 text-xs font-medium text-slate-200">
      <Icon className="h-3.5 w-3.5 text-sky-300" aria-hidden="true" />
      {children}
    </span>
  );
}

function EmptyRoomingState({
  passengerCount,
  onCreate,
}: {
  passengerCount: number;
  onCreate: () => void;
}) {
  return (
    <Card>
      <CardContent className="p-10 text-center sm:p-12">
        <Hotel
          className="mx-auto h-10 w-10 text-blue-500"
          aria-hidden="true"
        />
        <h2 className="mt-4 text-lg font-semibold text-slate-900">
          Add the first hotel stay
        </h2>
        <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-slate-500">
          {passengerCount} confirmed passenger
          {passengerCount === 1 ? " is" : "s are"} ready. Add a hotel, choose
          who stays there, mark any VIPs, and auto-allocate rooms.
        </p>
        <Button type="button" className="mt-5" onClick={onCreate}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          Add hotel
        </Button>
      </CardContent>
    </Card>
  );
}

function RoomingLoading() {
  return (
    <div className="space-y-5" aria-label="Loading rooming workspace">
      <Skeleton className="h-36 rounded-2xl" />
      <Skeleton className="h-[72px] rounded-xl" />
      <Skeleton className="h-16 rounded-xl" />
      <Skeleton className="h-32 rounded-xl" />
      <Skeleton className="h-96" />
    </div>
  );
}

function CheckinLoading() {
  return (
    <div className="space-y-4" role="status" aria-label="Loading hotel check-in desk">
      <Skeleton className="h-16 rounded-xl" />
      <Skeleton className="h-24 rounded-xl" />
      <Skeleton className="h-72 rounded-xl" />
    </div>
  );
}
