import { CalendarCheck2, CalendarDays, Plane, Users, type LucideIcon } from "lucide-react";

export interface CompanyOverviewValues {
  completedGroups: number | null;
  activeGroups: number | null;
  passengerTrips: number | null;
  uniquePeople: number | null;
}

/** Presentation only: the server supplies the agreed counting rules. */
export function CompanyOverviewStats({ values, loading = false }: { values: CompanyOverviewValues; loading?: boolean }) {
  const metrics: { label: string; value: number | null; icon: LucideIcon; color: string }[] = [
    { label: "Completed groups", value: values.completedGroups, icon: CalendarCheck2, color: "bg-emerald-50 text-emerald-700" },
    { label: "Active groups", value: values.activeGroups, icon: CalendarDays, color: "bg-blue-50 text-blue-700" },
    { label: "Passenger trips", value: values.passengerTrips, icon: Plane, color: "bg-violet-50 text-violet-700" },
    { label: "Unique people", value: values.uniquePeople, icon: Users, color: "bg-amber-50 text-amber-700" },
  ];
  return <section aria-label="Company overview" aria-busy={loading} className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
    {metrics.map(({ label, value, icon: Icon, color }) => <div key={label} className="min-w-0 rounded-xl border border-slate-200 bg-white px-3.5 py-3 shadow-sm sm:px-4">
      <div className="flex items-center justify-between gap-2"><p className="text-xs font-medium leading-5 text-slate-500">{label}</p><span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${color}`}><Icon className="h-3.5 w-3.5" aria-hidden="true" /></span></div>
      {loading ? <div className="mt-2 h-7 w-16 rounded bg-slate-100 motion-safe:animate-pulse" aria-label={`Loading ${label.toLowerCase()}`} /> : <p className="mt-1 text-2xl font-semibold tabular-nums tracking-tight text-slate-950">{value === null ? "—" : value.toLocaleString()}</p>}
    </div>)}
  </section>;
}
