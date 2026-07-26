"use client";

import {
  ArrowLeft,
  BedDouble,
  Crown,
  Edit3,
  Hotel,
  Plus,
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
import { Badge, Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/shared/page-header";
import { ROUTES } from "@/constants/routes";
import { operationsApi, type RoomingHotel } from "../api/operations.api";
import {
  useRoomingActions,
  useRoomingPriorityFields,
  useRoomingWorkspace,
} from "../hooks/use-operations";
import { HotelCheckinDashboard } from "./hotel-checkin-dashboard";
import { RoomingAutoAllocation } from "./rooming-auto-allocation";
import { roomingErrorMessage } from "./rooming-error-message";
import { RoomingPassengerHotelAllocation } from "./rooming-passenger-hotel-allocation";

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
      <div
        role="alert"
        className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
      >
        Rooming workspace could not be loaded. Refresh the page and try again.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={data.group_name}
        description={
          data.destination
            ? `Hotel allocation and automatic rooming - ${data.destination}`
            : "Hotel allocation and automatic rooming"
        }
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setShowHotelDialog(true)}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              Add hotel
            </Button>
          </div>
        )}
      />

      <Link
        href={ROUTES.dashboard.rooming as never}
        className="inline-flex w-fit items-center gap-2 text-sm font-medium text-slate-600 hover:text-blue-700"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        All rooming lists
      </Link>

      {actionError && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
        >
          {actionError}
        </div>
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
            className="overflow-x-auto border-b border-slate-200 pb-3"
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
                  className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${
                    hotel.id === activeHotel?.id
                      ? "border-blue-600 bg-blue-600 text-white"
                      : "border-slate-200 bg-white text-slate-700 hover:border-blue-200 hover:bg-blue-50"
                  }`}
                >
                  {hotel.hotel_name}
                  <span
                    className={`ml-2 rounded-full px-2 py-0.5 text-xs ${
                      hotel.id === activeHotel?.id
                        ? "bg-white/20 text-white"
                        : "bg-slate-100 text-slate-600"
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
                className="flex gap-2 border-b border-slate-200"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={hotelTab === "allocation"}
                  onClick={() => setHotelTab("allocation")}
                  className={`px-3 py-2 text-sm font-medium ${
                    hotelTab === "allocation"
                      ? "border-b-2 border-blue-600 text-blue-700"
                      : "text-slate-500 hover:text-slate-800"
                  }`}
                >
                  Allocation
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={hotelTab === "checkins"}
                  onClick={() => setHotelTab("checkins")}
                  className={`px-3 py-2 text-sm font-medium ${
                    hotelTab === "checkins"
                      ? "border-b-2 border-blue-600 text-blue-700"
                      : "text-slate-500 hover:text-slate-800"
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
                  <Card>
                    <CardContent className="p-10 text-center text-sm text-slate-500">
                      Run auto allocation again before opening hotel check-in.
                      Hotel membership or VIP status may have changed since the
                      previous room plan.
                    </CardContent>
                  </Card>
                )
              ) : (
                <div className="space-y-5">
                  <RoomingPassengerHotelAllocation
                    key={activeHotel.id}
                    workspace={data}
                    activeHotel={activeHotel}
                    isAssigning={actions.selectHotelPassengers.isPending}
                    isUpdatingVip={actions.setPassengerVip.isPending}
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

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-4 sm:p-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
            <Hotel className="h-5 w-5" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h2 className="truncate font-semibold text-slate-900">
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
      </CardContent>
    </Card>
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
      <Skeleton className="h-16" />
      <Skeleton className="h-14" />
      <Skeleton className="h-28" />
      <Skeleton className="h-96" />
    </div>
  );
}
