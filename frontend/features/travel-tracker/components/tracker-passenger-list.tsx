import { Check, CheckCircle2, Circle, LoaderCircle, Plane, Stamp } from "lucide-react";
import type { KeyboardEvent } from "react";
import { TRACKER_COPY, isPassengerMarked } from "../model";
import type { TrackerKind, TrackerPassenger } from "../types";

export function TrackerPassengerList({ passengers, track, pending, disabled, onMark }: {
  passengers: TrackerPassenger[]; track: TrackerKind; pending: Record<string, boolean>;
  disabled: boolean; onMark: (passenger: TrackerPassenger) => void;
}) {
  const copy = TRACKER_COPY[track];
  const navigateRows = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const buttons = Array.from(event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[data-passenger-row]:not(:disabled)") ?? []);
    const index = buttons.indexOf(event.currentTarget);
    buttons[index + (event.key === "ArrowDown" ? 1 : -1)]?.focus();
  };
  return (
    <div className="divide-y divide-slate-100" aria-label={`${copy.label} passenger list`}>
      {passengers.map((passenger) => {
        const key = `${track}:${passenger.id}`;
        const saving = Object.hasOwn(pending, key);
        const marked = saving ? pending[key] : isPassengerMarked(passenger, track);
        return (
          <button key={passenger.id} type="button" data-passenger-row data-passenger-id={passenger.id} aria-label={`${passenger.full_name}: ${marked ? "move to pending" : copy.action}`} aria-pressed={marked} aria-busy={saving} disabled={disabled || saving} onClick={() => onMark(passenger)} onKeyDown={navigateRows} className={`group flex min-h-24 w-full items-center gap-3 px-4 py-3 text-left transition-colors focus-visible:relative focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 disabled:cursor-wait sm:min-h-20 sm:gap-4 sm:px-5 ${marked ? "bg-emerald-50/40 hover:bg-emerald-50" : "bg-white hover:bg-blue-50/60"}`}>
            <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border ${marked ? "border-emerald-200 bg-emerald-100 text-emerald-700" : "border-slate-200 bg-slate-50 text-slate-400 group-hover:border-blue-200 group-hover:bg-blue-100 group-hover:text-blue-700"}`}>{saving ? <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden="true" /> : marked ? <CheckCircle2 className="h-5 w-5" aria-hidden="true" /> : <Circle className="h-5 w-5" aria-hidden="true" />}</span>
            <span className="grid min-w-0 flex-1 gap-1 sm:grid-cols-[minmax(0,1fr)_minmax(0,.75fr)] sm:gap-4">
              <span className="min-w-0"><span className="block break-words text-sm font-semibold text-slate-950">{passenger.full_name || "Unnamed passenger"}</span><span className="mt-1 block break-words font-mono text-xs text-slate-500">{passenger.passport_number || "Passport not provided"}{passenger.departure_city ? ` · ${passenger.departure_city}` : ""}</span></span>
              <span className="hidden min-w-0 sm:block"><span className="block truncate text-xs text-slate-600">{passenger.phone || passenger.email || "Contact not provided"}</span><span className="mt-1.5 flex items-center gap-3 text-[11px] text-slate-500"><span className="inline-flex items-center gap-1"><Stamp className={`h-3 w-3 ${passenger.visa_applied ? "text-emerald-600" : "text-slate-400"}`} />Visa {passenger.visa_applied ? "applied" : "pending"}</span><span className="inline-flex items-center gap-1"><Plane className={`h-3 w-3 ${passenger.flight_booked ? "text-emerald-600" : "text-slate-400"}`} />Flight {passenger.flight_booked ? "booked" : "pending"}</span></span></span>
            </span>
            <span className={`flex max-w-24 shrink-0 flex-col items-end gap-1 text-right text-xs font-semibold sm:max-w-none ${marked ? "text-emerald-700" : "text-blue-700"}`}><span>{saving ? "Saving…" : marked ? copy.marked : "Tap to mark"}</span><span className="text-[10px] font-normal text-slate-400">{marked && !saving ? "Tap to undo" : copy.pending}</span>{marked && <Check className="hidden h-3.5 w-3.5 sm:block" aria-hidden="true" />}</span>
          </button>
        );
      })}
    </div>
  );
}
