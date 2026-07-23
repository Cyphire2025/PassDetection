"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  BedDouble,
  CheckCircle2,
  Flashlight,
  FlashlightOff,
  Hotel,
  KeyRound,
  Loader2,
  LogIn,
  MessageSquarePlus,
  PackageCheck,
  RotateCw,
  ScanLine,
  SwitchCamera,
  WifiOff,
} from "lucide-react";
import { Button } from "@/components/ui";
import { operationsApi, type HotelCheckinPassenger } from "@/features/operations/api/operations.api";
import { useContinuousQrScanner } from "../hooks/use-continuous-qr-scanner";
import {
  selectHasHydrated,
  selectIsAuthenticated,
  selectUser,
  useAuthStore,
} from "@/stores/auth.store";
import { ROUTES } from "@/constants/routes";
import { CoordinatorFrame, CoordinatorHydrationState } from "./coordinator-mobile-shell";
import { useNetworkStatus } from "../hooks/use-network-status";

type ScanResult = {
  message: string;
  checkin: HotelCheckinPassenger | null;
  status: string;
  updatedAt: number;
};

type CheckinUpdateBody = {
  key_issued?: boolean;
  welcome_letter_issued?: boolean;
  remarks?: string;
};

const ERROR_STATUSES = new Set(["invalid", "expired", "revoked", "inactive", "wrong_group", "wrong_hotel", "unallocated", "error"]);

export function CoordinatorHotelCheckin({ groupId }: { groupId: string }) {
  const router = useRouter();
  const user = useAuthStore(selectUser);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const hasHydrated = useAuthStore(selectHasHydrated);
  const clearSession = useAuthStore((state) => state.clearSession);
  const isCoordinator = isAuthenticated && user?.role === "agency_coordinator";
  const isOnline = useNetworkStatus();
  const [hotels, setHotels] = useState<Array<{ id: string; hotel_name: string }>>([]);
  const [hotelsLoading, setHotelsLoading] = useState(true);
  const [hotelsError, setHotelsError] = useState<string | null>(null);
  const [hotelId, setHotelId] = useState<string | null>(null);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [remarkOpen, setRemarkOpen] = useState(false);
  const [remarkText, setRemarkText] = useState("");
  const [savingAction, setSavingAction] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [scanPending, setScanPending] = useState(false);
  const [awaitingNextPassenger, setAwaitingNextPassenger] = useState(false);
  const processedScanIdRef = useRef<string | null>(null);
  const scanLockedRef = useRef(false);
  const hotelIdRef = useRef<string | null>(null);
  const mountedRef = useRef(true);
  const hotelLoadGenerationRef = useRef(0);
  const queuedHotelScansRef = useRef(0);
  const scanPipelineRef = useRef<Promise<void>>(Promise.resolve());
  const {
    devices,
    errorMessage,
    isTorchOn,
    latestScan,
    selectedDeviceId,
    setSelectedDeviceId,
    startScanner,
    status,
    stopScanner,
    supportsTorch,
    toggleTorch,
    videoRef,
  } = useContinuousQrScanner({
    canAutoResume: () => (
      !scanLockedRef.current
      && hotelIdRef.current !== null
      && navigator.onLine
    ),
  });

  const loadHotels = useCallback(() => {
    const generation = hotelLoadGenerationRef.current + 1;
    hotelLoadGenerationRef.current = generation;
    setHotelsLoading(true);
    setHotelsError(null);
    void operationsApi.roomingWorkspace(groupId)
      .then((data) => {
        if (mountedRef.current && hotelLoadGenerationRef.current === generation) {
          setHotels(data.hotels);
        }
      })
      .catch(() => {
        if (mountedRef.current && hotelLoadGenerationRef.current === generation) {
          setHotelsError("Hotels could not be loaded. Check the connection and try again.");
        }
      })
      .finally(() => {
        if (mountedRef.current && hotelLoadGenerationRef.current === generation) {
          setHotelsLoading(false);
        }
      });
  }, [groupId]);

  useEffect(() => {
    mountedRef.current = true;
    const loadTimer = hasHydrated && isCoordinator
      ? window.setTimeout(loadHotels, 0)
      : null;
    return () => {
      if (loadTimer !== null) window.clearTimeout(loadTimer);
      mountedRef.current = false;
      hotelLoadGenerationRef.current += 1;
    };
  }, [hasHydrated, isCoordinator, loadHotels]);

  useEffect(() => {
    hotelIdRef.current = hotelId;
    if (!hotelId || !isOnline || awaitingNextPassenger) {
      stopScanner();
      return;
    }
    void startScanner();
    return () => stopScanner();
  }, [awaitingNextPassenger, hotelId, isOnline, startScanner, stopScanner]);

  useEffect(() => {
    if (
      !latestScan
      || !hotelId
      || scanLockedRef.current
      || processedScanIdRef.current === latestScan.id
    ) return;
    scanLockedRef.current = true;
    processedScanIdRef.current = latestScan.id;
    setAwaitingNextPassenger(true);
    stopScanner();
    const requestedHotelId = hotelId;
    queuedHotelScansRef.current += 1;
    setScanPending(true);
    scanPipelineRef.current = scanPipelineRef.current
      .catch(() => undefined)
      .then(async () => {
        try {
          const response = await operationsApi.scanHotelCheckin(requestedHotelId, latestScan.text, latestScan.id);
          if (!mountedRef.current || hotelIdRef.current !== requestedHotelId) return;
          setRemarkOpen(false);
          setRemarkText(response.checkin?.remarks ?? "");
          setActionError(null);
          setResult({ ...response, updatedAt: Date.now() });
        } catch {
          if (!mountedRef.current || hotelIdRef.current !== requestedHotelId) return;
          setResult({
            status: "error",
            message: "Scan could not be saved. Check the connection and scan again.",
            checkin: null,
            updatedAt: Date.now(),
          });
        } finally {
          queuedHotelScansRef.current = Math.max(0, queuedHotelScansRef.current - 1);
          if (mountedRef.current) setScanPending(queuedHotelScansRef.current > 0);
        }
      });
  }, [hotelId, latestScan, stopScanner]);

  const update = async (body: CheckinUpdateBody, action: string) => {
    if (!result?.checkin || savingAction || scanPending) return;
    const requestedHotelId = hotelId;
    const checkinId = result.checkin.checkin_id;
    setSavingAction(action);
    setActionError(null);
    stopScanner();
    try {
      const checkin = await operationsApi.updateHotelCheckin(checkinId, body);
      if (!mountedRef.current || hotelIdRef.current !== requestedHotelId) return;
      setResult((current) => current?.checkin?.checkin_id === checkinId
        ? { ...current, checkin, message: "Saved.", updatedAt: Date.now() }
        : current);
      setRemarkText(checkin.remarks ?? "");
      setRemarkOpen(false);
    } catch {
      if (mountedRef.current && hotelIdRef.current === requestedHotelId) {
        setActionError("The check-in update was not saved. Please try again.");
      }
    } finally {
      if (mountedRef.current && hotelIdRef.current === requestedHotelId) {
        setSavingAction(null);
      }
    }
  };

  const openRemark = () => {
    setRemarkText(result?.checkin?.remarks ?? "");
    setActionError(null);
    setRemarkOpen(true);
    stopScanner();
  };

  const cancelRemark = () => {
    setRemarkOpen(false);
    setActionError(null);
  };

  const scanNextPassenger = () => {
    if (!isOnline || !hotelId || savingAction) return;
    scanLockedRef.current = false;
    processedScanIdRef.current = null;
    setResult(null);
    setActionError(null);
    setRemarkOpen(false);
    setRemarkText("");
    setAwaitingNextPassenger(false);
  };

  const selectHotel = (nextHotelId: string) => {
    stopScanner();
    scanLockedRef.current = false;
    processedScanIdRef.current = null;
    setResult(null);
    setActionError(null);
    setRemarkOpen(false);
    setAwaitingNextPassenger(false);
    setHotelId(nextHotelId);
  };

  const changeHotel = () => {
    stopScanner();
    scanLockedRef.current = false;
    hotelIdRef.current = null;
    processedScanIdRef.current = null;
    setHotelId(null);
    setResult(null);
    setActionError(null);
    setRemarkOpen(false);
    setAwaitingNextPassenger(false);
  };

  const switchCamera = () => {
    if (awaitingNextPassenger || !isOnline || devices.length < 2) return;
    const currentIndex = devices.findIndex((device) => device.deviceId === selectedDeviceId);
    const nextDevice = devices[(currentIndex + 1 + devices.length) % devices.length];
    stopScanner();
    setSelectedDeviceId(nextDevice.deviceId);
    void startScanner();
  };

  const retryCamera = () => {
    if (awaitingNextPassenger || !hotelId || !isOnline) return;
    void startScanner();
  };

  if (!hasHydrated) {
    return <CoordinatorHydrationState label="Loading hotel check-in" />;
  }

  if (!isCoordinator) {
    return (
      <CoordinatorFrame>
        <div className="flex flex-1 flex-col items-center justify-center px-5 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-50 text-blue-600">
            <LogIn className="h-7 w-7" aria-hidden="true" />
          </div>
          <h1 className="mt-5 text-xl font-bold text-slate-950">Coordinator login required</h1>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            Sign in with a coordinator account to use hotel check-in.
          </p>
          <Button
            type="button"
            className="mt-6 h-12 w-full max-w-sm"
            onClick={() => {
              if (isAuthenticated) {
                void clearSession();
                return;
              }
              router.push(ROUTES.auth.coordinatorLogin(`/coordinator/groups/${groupId}/hotel-checkin`) as never);
            }}
          >
            {isAuthenticated ? "Switch Account" : "Login"}
          </Button>
        </div>
      </CoordinatorFrame>
    );
  }

  if (!hotelId) {
    return (
      <HotelPicker
        groupId={groupId}
        hotels={hotels}
        isLoading={hotelsLoading}
        error={hotelsError}
        isOnline={isOnline}
        onRetry={loadHotels}
        onSelect={selectHotel}
      />
    );
  }

  const hotelName = hotels.find((hotel) => hotel.id === hotelId)?.hotel_name ?? "Selected hotel";

  return (
    <div
      data-coordinator-fixed-viewport
      className="bg-slate-50 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] text-slate-950"
    >
      <div className="mx-auto flex h-full w-full max-w-lg flex-col">
        <header className="shrink-0 border-b border-slate-200 bg-white px-4 pb-2.5 pt-[max(0.625rem,env(safe-area-inset-top))]">
          <div className="flex items-center justify-between gap-3">
            <button onClick={changeHotel} className="inline-flex min-h-11 items-center gap-2 rounded-lg pr-2 text-sm font-medium text-slate-600">
              <ArrowLeft className="h-4 w-4" /> Change hotel
            </button>
            <p className="min-w-0 truncate text-right text-[11px] font-semibold uppercase tracking-wide text-blue-600">
              Hotel Check-in / {isOnline ? awaitingNextPassenger ? "review" : status : "offline"}
            </p>
          </div>
          <div className="mt-1 flex items-center justify-between gap-3">
            <h1 className="text-lg font-bold leading-tight text-slate-950">{hotelName}</h1>
            {scanPending && <Loader2 className="h-5 w-5 animate-spin text-blue-600" />}
          </div>
        </header>

        <main className="grid min-h-0 flex-1 grid-rows-[minmax(0,11fr)_minmax(0,9fr)]">
          <section className="relative min-h-0 overflow-hidden bg-slate-950">
            <video ref={videoRef} className="h-full w-full object-cover" muted playsInline autoPlay />
            <div className="pointer-events-none absolute inset-0 grid place-items-center bg-slate-950/25">
              <div className="grid size-[min(66vw,14rem,38dvh)] place-items-center rounded-3xl border-4 border-white/85">
                <ScanLine className="h-10 w-10 text-white" />
              </div>
            </div>
            <div className="absolute left-3 top-3 rounded-full bg-white/90 px-3 py-1 text-xs font-semibold text-slate-700">
              Keep QR inside frame
            </div>
            {!awaitingNextPassenger && (
              <div className="absolute right-3 top-3 flex gap-2">
              {supportsTorch && (
                <button
                  type="button"
                  className="inline-flex h-11 w-11 items-center justify-center rounded-full bg-white/95 text-slate-800 shadow"
                  aria-label={isTorchOn ? "Turn torch off" : "Turn torch on"}
                  onClick={() => void toggleTorch()}
                >
                  {isTorchOn
                    ? <FlashlightOff className="h-5 w-5" aria-hidden="true" />
                    : <Flashlight className="h-5 w-5" aria-hidden="true" />}
                </button>
              )}
              {devices.length > 1 && (
                <button
                  type="button"
                  className="inline-flex h-11 w-11 items-center justify-center rounded-full bg-white/95 text-slate-800 shadow"
                  aria-label="Switch camera"
                  onClick={switchCamera}
                >
                  <SwitchCamera className="h-5 w-5" aria-hidden="true" />
                </button>
              )}
              </div>
            )}
          </section>

          <section className="min-h-0 overflow-y-auto overscroll-contain border-t border-slate-200 bg-white p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
            {!isOnline && (
              <div className="mb-3 flex gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                <WifiOff className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                {awaitingNextPassenger
                  ? "This passenger remains paused for review. Reconnect to save desk updates, then choose Scan next passenger when finished."
                  : "Hotel check-in needs a connection. The camera will resume automatically when you reconnect."}
              </div>
            )}
            {errorMessage && !awaitingNextPassenger && (
              <div className="mb-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                <p>{errorMessage}</p>
                <Button
                  type="button"
                  variant="secondary"
                  className="mt-3 h-11 w-full"
                  leftIcon={<RotateCw className="h-4 w-4" aria-hidden="true" />}
                  onClick={retryCamera}
                >
                  Retry camera
                </Button>
              </div>
            )}
            {actionError && (
              <p role="alert" className="mb-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {actionError}
              </p>
            )}
            {scanPending && (
              <p role="status" aria-live="polite" className="mb-3 rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
                Validating passenger check-in…
              </p>
            )}
            {!errorMessage && (
              <div aria-live="polite">
                <CheckinDetails
                  hotelName={hotelName}
                  result={result}
                  remarkOpen={remarkOpen}
                  remarkText={remarkText}
                  savingAction={savingAction}
                  actionsDisabled={scanPending || savingAction !== null || !isOnline}
                  onRemarkTextChange={setRemarkText}
                  onOpenRemark={openRemark}
                  onCancelRemark={cancelRemark}
                  onScanNext={scanNextPassenger}
                  onUpdate={update}
                />
              </div>
            )}
          </section>
        </main>
      </div>
    </div>
  );
}

function HotelPicker({
  groupId,
  hotels,
  isLoading,
  error,
  isOnline,
  onRetry,
  onSelect,
}: {
  groupId: string;
  hotels: Array<{ id: string; hotel_name: string }>;
  isLoading: boolean;
  error: string | null;
  isOnline: boolean;
  onRetry: () => void;
  onSelect: (hotelId: string) => void;
}) {
  return (
    <CoordinatorFrame>
      <main className="flex-1 px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-[max(1rem,env(safe-area-inset-top))]">
        <Link href={`/coordinator/groups/${groupId}`} className="inline-flex min-h-11 items-center gap-2 rounded-lg pr-3 text-sm font-medium text-slate-600">
          <ArrowLeft className="h-4 w-4" /> Back to group
        </Link>
        <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
            <Hotel className="h-5 w-5" />
          </span>
          <h1 className="mt-4 text-2xl font-bold text-slate-950">Hotel Check-in</h1>
          <p className="mt-2 text-sm leading-6 text-slate-500">Select the arrival hotel once. The scanner opens on the next screen and stays active.</p>
        </div>

        <div className="mt-4 space-y-3">
          {!isOnline && (
            <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              Reconnect to load hotels and start check-in.
            </p>
          )}
          {error && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              <p>{error}</p>
              <Button
                type="button"
                variant="secondary"
                className="mt-3 h-11 w-full"
                disabled={!isOnline}
                isLoading={isLoading}
                leftIcon={<RotateCw className="h-4 w-4" aria-hidden="true" />}
                onClick={onRetry}
              >
                Try again
              </Button>
            </div>
          )}
          {isLoading && !error && (
            <>
              <div className="h-16 animate-pulse rounded-xl border border-slate-200 bg-white" />
              <div className="h-16 animate-pulse rounded-xl border border-slate-200 bg-white" />
            </>
          )}
          {!isLoading && !error && hotels.map((hotel) => (
            <button
              key={hotel.id}
              type="button"
              disabled={!isOnline}
              onClick={() => onSelect(hotel.id)}
              className="flex min-h-16 w-full items-center justify-between rounded-xl border border-slate-200 bg-white p-4 text-left font-semibold text-slate-900 shadow-sm transition-colors hover:border-blue-200 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {hotel.hotel_name}
              <ArrowLeft className="h-4 w-4 rotate-180 text-slate-400" />
            </button>
          ))}
          {!isLoading && !error && hotels.length === 0 && <p className="rounded-xl border border-dashed border-slate-300 bg-white p-4 text-sm text-slate-500">No hotels have been added to this group yet.</p>}
        </div>
      </main>
    </CoordinatorFrame>
  );
}

function CheckinDetails({
  hotelName,
  result,
  remarkOpen,
  remarkText,
  savingAction,
  actionsDisabled,
  onRemarkTextChange,
  onOpenRemark,
  onCancelRemark,
  onScanNext,
  onUpdate,
}: {
  hotelName: string;
  result: ScanResult | null;
  remarkOpen: boolean;
  remarkText: string;
  savingAction: string | null;
  actionsDisabled: boolean;
  onRemarkTextChange: (value: string) => void;
  onOpenRemark: () => void;
  onCancelRemark: () => void;
  onScanNext: () => void;
  onUpdate: (body: CheckinUpdateBody, action: string) => Promise<void>;
}) {
  const item = result?.checkin;

  if (!result) {
    return (
      <div className="flex h-full min-h-52 flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-center">
        <ScanLine className="h-8 w-8 text-blue-500" />
        <h2 className="mt-3 font-semibold text-slate-950">Passenger details will show here</h2>
        <p className="mt-1 text-sm text-slate-500">Scan a passenger QR. The camera pauses as soon as a code is accepted so this desk record stays stable.</p>
      </div>
    );
  }

  if (!item) {
    return (
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Check required</p>
        <p className="mt-1 text-lg font-bold text-slate-950">{statusLabel(result.status)}</p>
        <p className="mt-1 text-sm text-amber-900">{result.message}</p>
        <Button
          type="button"
          variant="secondary"
          className="mt-4 h-11 w-full"
          disabled={actionsDisabled}
          onClick={onScanNext}
        >
          <ScanLine className="h-4 w-4" aria-hidden="true" /> Scan again
        </Button>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className={`text-xs font-semibold uppercase tracking-wide ${ERROR_STATUSES.has(result.status) ? "text-amber-700" : "text-emerald-700"}`}>{statusLabel(result.status)}</p>
          <h2 className="text-lg font-bold leading-tight text-slate-950">{item.passenger_name}</h2>
          <p className="mt-0.5 text-sm text-slate-600">{hotelName}</p>
        </div>
        {(item.is_vip || item.has_special_request) && <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800">VIP</span>}
      </div>

      <div className="mt-2 rounded-xl bg-slate-50 p-2.5 text-sm">
        <p className="flex items-center gap-2 font-semibold text-slate-950"><BedDouble className="h-4 w-4 text-blue-600" /> Room {item.room_number} - {item.room_type}</p>
        <p className="mt-1 text-slate-600">{item.roommates.length ? `Roommates: ${item.roommates.join(", ")}` : "No roommates assigned."}</p>
      </div>

      <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
        <StatusPill label="Checked in" value={item.checked_in} />
        <StatusPill label="Key" value={item.key_issued} />
        <StatusPill label="Welcome" value={item.welcome_letter_issued} />
      </div>

      {(item.room_has_missing_occupants || item.is_vip || item.has_special_request) && (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs font-medium text-amber-900">
          {item.room_has_missing_occupants && <p>Room has missing occupants.</p>}
          {(item.is_vip || item.has_special_request) && <p>VIP or special request passenger.</p>}
        </div>
      )}

      {item.remarks && !remarkOpen && <p className="mt-3 rounded-lg bg-slate-50 p-2 text-xs text-slate-700">Remark: {item.remarks}</p>}

      {remarkOpen ? (
        <div className="mt-3 space-y-2">
          <label htmlFor="hotel-checkin-remark" className="text-sm font-semibold text-slate-700">
            Desk remark
          </label>
          <textarea
            id="hotel-checkin-remark"
            className="min-h-24 w-full resize-y rounded-lg border border-slate-300 px-3 py-2 text-base text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            value={remarkText}
            onChange={(event) => onRemarkTextChange(event.target.value)}
            placeholder="Add desk remark"
            maxLength={1000}
            autoFocus
          />
          <div className="grid grid-cols-2 gap-2">
            <Button className="h-11" variant="secondary" disabled={savingAction !== null} onClick={onCancelRemark}>Cancel</Button>
            <Button className="h-11" disabled={actionsDisabled} isLoading={savingAction === "remarks"} onClick={() => void onUpdate({ remarks: remarkText.trim() }, "remarks")}>Save remark</Button>
          </div>
        </div>
      ) : (
        <div className="mt-2 grid gap-2">
          <Button className="h-11" disabled={actionsDisabled} isLoading={savingAction === "both"} onClick={() => void onUpdate({ key_issued: true, welcome_letter_issued: true }, "both")}>
            <PackageCheck className="h-5 w-5" /> Key + Welcome kit given
          </Button>
          <div className="grid grid-cols-2 gap-2">
            <Button className="h-11" variant="secondary" disabled={actionsDisabled} isLoading={savingAction === "key"} onClick={() => void onUpdate({ key_issued: true }, "key")}>
              <KeyRound className="h-4 w-4" /> Only key
            </Button>
            <Button className="h-11" variant="secondary" disabled={actionsDisabled} isLoading={savingAction === "welcome"} onClick={() => void onUpdate({ welcome_letter_issued: true }, "welcome")}>
              Only welcome kit
            </Button>
          </div>
          <Button variant="ghost" className="h-11 text-slate-700" disabled={actionsDisabled} onClick={onOpenRemark}>
            <MessageSquarePlus className="h-4 w-4" /> Add remark
          </Button>
        </div>
      )}

      <Button
        type="button"
        variant="secondary"
        className="mt-3 h-11 w-full"
        disabled={actionsDisabled || remarkOpen}
        onClick={onScanNext}
      >
        <ScanLine className="h-4 w-4" aria-hidden="true" /> Scan next passenger
      </Button>
    </div>
  );
}

function StatusPill({ label, value }: { label: string; value: boolean }) {
  return (
    <div className={`rounded-lg px-2 py-1.5 text-center ${value ? "bg-emerald-50 text-emerald-800" : "bg-slate-100 text-slate-600"}`}>
      {value ? <CheckCircle2 className="mx-auto h-4 w-4" /> : <span className="block font-semibold">No</span>}
      <p className="mt-0.5">{value ? "Yes" : label}</p>
      {value && <p>{label}</p>}
    </div>
  );
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    checked_in: "Checked in",
    already_checked_in: "Already checked in",
    invalid: "Invalid QR",
    expired: "Expired QR",
    revoked: "Revoked QR",
    inactive: "Inactive QR",
    wrong_group: "Wrong group",
    wrong_hotel: "Wrong hotel",
    unallocated: "Unallocated",
    error: "Scan error",
  };
  return labels[status] ?? status;
}
