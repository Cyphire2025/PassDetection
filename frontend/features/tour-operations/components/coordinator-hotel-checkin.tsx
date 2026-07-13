"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ArrowLeft, BedDouble, CheckCircle2, Hotel, KeyRound, Loader2, MessageSquarePlus, PackageCheck, ScanLine } from "lucide-react";
import { Button } from "@/components/ui";
import { operationsApi, type HotelCheckinPassenger } from "@/features/operations/api/operations.api";
import { useContinuousQrScanner } from "../hooks/use-continuous-qr-scanner";

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
  const [hotels, setHotels] = useState<Array<{ id: string; hotel_name: string }>>([]);
  const [hotelsLoading, setHotelsLoading] = useState(true);
  const [hotelId, setHotelId] = useState<string | null>(null);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [remarkOpen, setRemarkOpen] = useState(false);
  const [remarkText, setRemarkText] = useState("");
  const [savingAction, setSavingAction] = useState<string | null>(null);
  const [scanPending, setScanPending] = useState(false);
  const seen = useRef(new Set<string>());
  const { videoRef, latestScan, startScanner, status, errorMessage } = useContinuousQrScanner();

  useEffect(() => {
    let cancelled = false;
    void operationsApi.roomingWorkspace(groupId)
      .then((data) => {
        if (!cancelled) setHotels(data.hotels);
      })
      .finally(() => {
        if (!cancelled) setHotelsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [groupId]);

  useEffect(() => {
    if (hotelId) void startScanner();
  }, [hotelId, startScanner]);

  useEffect(() => {
    if (!latestScan || !hotelId || seen.current.has(latestScan.id)) return;
    seen.current.add(latestScan.id);
    setScanPending(true);
    void operationsApi.scanHotelCheckin(hotelId, latestScan.text, latestScan.id)
      .then((response) => {
        setRemarkOpen(false);
        setRemarkText(response.checkin?.remarks ?? "");
        setResult({ ...response, updatedAt: Date.now() });
      })
      .catch(() => setResult({ status: "error", message: "Scan could not be saved.", checkin: null, updatedAt: Date.now() }))
      .finally(() => setScanPending(false));
  }, [hotelId, latestScan]);

  const update = async (body: CheckinUpdateBody, action: string) => {
    if (!result?.checkin) return;
    setSavingAction(action);
    try {
      const checkin = await operationsApi.updateHotelCheckin(result.checkin.checkin_id, body);
      setResult((current) => current ? { ...current, checkin, message: "Saved.", updatedAt: Date.now() } : current);
      setRemarkText(checkin.remarks ?? "");
      setRemarkOpen(false);
    } finally {
      setSavingAction(null);
    }
  };

  const openRemark = () => {
    setRemarkText(result?.checkin?.remarks ?? "");
    setRemarkOpen(true);
  };

  if (!hotelId) {
    return <HotelPicker groupId={groupId} hotels={hotels} isLoading={hotelsLoading} onSelect={setHotelId} />;
  }

  const hotelName = hotels.find((hotel) => hotel.id === hotelId)?.hotel_name ?? "Selected hotel";

  return (
    <div className="h-[100svh] overflow-hidden bg-slate-50 text-slate-950">
      <div className="mx-auto flex h-full max-w-md flex-col">
        <header className="shrink-0 border-b border-slate-200 bg-white px-4 py-2.5">
          <div className="flex items-center justify-between gap-3">
            <button onClick={() => setHotelId(null)} className="inline-flex items-center gap-2 text-sm font-medium text-slate-600">
              <ArrowLeft className="h-4 w-4" /> Change hotel
            </button>
            <p className="shrink-0 text-[11px] font-semibold uppercase tracking-wide text-blue-600">Hotel Check-in / {status}</p>
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
              <div className="grid aspect-square w-56 max-w-[66vw] place-items-center rounded-3xl border-4 border-white/85">
                <ScanLine className="h-10 w-10 text-white" />
              </div>
            </div>
            <div className="absolute left-3 top-3 rounded-full bg-white/90 px-3 py-1 text-xs font-semibold text-slate-700">
              Keep QR inside frame
            </div>
          </section>

          <section className="min-h-0 overflow-y-auto border-t border-slate-200 bg-white p-3">
            {errorMessage ? (
              <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{errorMessage}</div>
            ) : (
              <CheckinDetails
                hotelName={hotelName}
                result={result}
                remarkOpen={remarkOpen}
                remarkText={remarkText}
                savingAction={savingAction}
                onRemarkTextChange={setRemarkText}
                onOpenRemark={openRemark}
                onCancelRemark={() => setRemarkOpen(false)}
                onUpdate={update}
              />
            )}
          </section>
        </main>
      </div>
    </div>
  );
}

function HotelPicker({ groupId, hotels, isLoading, onSelect }: { groupId: string; hotels: Array<{ id: string; hotel_name: string }>; isLoading: boolean; onSelect: (hotelId: string) => void }) {
  return (
    <div className="min-h-[100svh] bg-slate-50 p-4 text-slate-950">
      <div className="mx-auto max-w-md">
        <Link href={`/coordinator/groups/${groupId}`} className="inline-flex items-center gap-2 text-sm font-medium text-slate-600">
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
          {isLoading && (
            <>
              <div className="h-16 animate-pulse rounded-xl border border-slate-200 bg-white" />
              <div className="h-16 animate-pulse rounded-xl border border-slate-200 bg-white" />
            </>
          )}
          {!isLoading && hotels.map((hotel) => (
            <button key={hotel.id} onClick={() => onSelect(hotel.id)} className="flex w-full items-center justify-between rounded-xl border border-slate-200 bg-white p-4 text-left font-semibold text-slate-900 shadow-sm transition hover:border-blue-200 hover:bg-blue-50">
              {hotel.hotel_name}
              <ArrowLeft className="h-4 w-4 rotate-180 text-slate-400" />
            </button>
          ))}
          {!isLoading && hotels.length === 0 && <p className="rounded-xl border border-dashed border-slate-300 bg-white p-4 text-sm text-slate-500">No hotels have been added to this group yet.</p>}
        </div>
      </div>
    </div>
  );
}

function CheckinDetails({
  hotelName,
  result,
  remarkOpen,
  remarkText,
  savingAction,
  onRemarkTextChange,
  onOpenRemark,
  onCancelRemark,
  onUpdate,
}: {
  hotelName: string;
  result: ScanResult | null;
  remarkOpen: boolean;
  remarkText: string;
  savingAction: string | null;
  onRemarkTextChange: (value: string) => void;
  onOpenRemark: () => void;
  onCancelRemark: () => void;
  onUpdate: (body: CheckinUpdateBody, action: string) => Promise<void>;
}) {
  const item = result?.checkin;

  if (!result) {
    return (
      <div className="flex h-full min-h-52 flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-center">
        <ScanLine className="h-8 w-8 text-blue-500" />
        <h2 className="mt-3 font-semibold text-slate-950">Passenger details will show here</h2>
        <p className="mt-1 text-sm text-slate-500">Scan a passenger QR. The scanner stays active, and this panel will keep the latest passenger until the next scan.</p>
      </div>
    );
  }

  if (!item) {
    return (
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Check required</p>
        <p className="mt-1 text-lg font-bold text-slate-950">{statusLabel(result.status)}</p>
        <p className="mt-1 text-sm text-amber-900">{result.message}</p>
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
          <textarea
            className="min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            value={remarkText}
            onChange={(event) => onRemarkTextChange(event.target.value)}
            placeholder="Add desk remark"
            autoFocus
          />
          <div className="grid grid-cols-2 gap-2">
            <Button variant="secondary" onClick={onCancelRemark}>Cancel</Button>
            <Button isLoading={savingAction === "remarks"} onClick={() => void onUpdate({ remarks: remarkText }, "remarks")}>Save remark</Button>
          </div>
        </div>
      ) : (
        <div className="mt-2 grid gap-2">
          <Button className="h-11" isLoading={savingAction === "both"} onClick={() => void onUpdate({ key_issued: true, welcome_letter_issued: true }, "both")}>
            <PackageCheck className="h-5 w-5" /> Key + Welcome kit given
          </Button>
          <div className="grid grid-cols-2 gap-2">
            <Button variant="secondary" isLoading={savingAction === "key"} onClick={() => void onUpdate({ key_issued: true }, "key")}>
              <KeyRound className="h-4 w-4" /> Only key
            </Button>
            <Button variant="secondary" isLoading={savingAction === "welcome"} onClick={() => void onUpdate({ welcome_letter_issued: true }, "welcome")}>
              Only welcome kit
            </Button>
          </div>
          <Button variant="ghost" className="text-slate-700" onClick={onOpenRemark}>
            <MessageSquarePlus className="h-4 w-4" /> Add remark
          </Button>
        </div>
      )}
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
