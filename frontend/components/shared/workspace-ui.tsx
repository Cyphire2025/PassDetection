import type { ReactNode } from "react";
import {
  AlertCircle,
  ArrowRight,
  Search,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";

type WorkspaceAccent = "sky" | "cyan" | "emerald" | "lime" | "amber" | "violet";
type WorkspaceMetricTone = "default" | "attention" | "success" | "info";

const ACCENT_STYLES: Record<WorkspaceAccent, { icon: string; glow: string; eyebrow: string }> = {
  sky: {
    icon: "border-sky-300/20 bg-sky-300/10 text-sky-200",
    glow: "bg-[radial-gradient(circle_at_center,rgba(56,189,248,0.2),transparent_68%)]",
    eyebrow: "text-sky-300",
  },
  cyan: {
    icon: "border-cyan-300/20 bg-cyan-300/10 text-cyan-200",
    glow: "bg-[radial-gradient(circle_at_center,rgba(34,211,238,0.18),transparent_68%)]",
    eyebrow: "text-cyan-300",
  },
  emerald: {
    icon: "border-emerald-300/20 bg-emerald-300/10 text-emerald-200",
    glow: "bg-[radial-gradient(circle_at_center,rgba(52,211,153,0.17),transparent_68%)]",
    eyebrow: "text-emerald-300",
  },
  lime: {
    icon: "border-lime-300/20 bg-lime-300/10 text-lime-200",
    glow: "bg-[radial-gradient(circle_at_center,rgba(163,230,53,0.15),transparent_68%)]",
    eyebrow: "text-lime-300",
  },
  amber: {
    icon: "border-amber-300/20 bg-amber-300/10 text-amber-200",
    glow: "bg-[radial-gradient(circle_at_center,rgba(251,191,36,0.15),transparent_68%)]",
    eyebrow: "text-amber-300",
  },
  violet: {
    icon: "border-violet-300/20 bg-violet-300/10 text-violet-200",
    glow: "bg-[radial-gradient(circle_at_center,rgba(167,139,250,0.18),transparent_68%)]",
    eyebrow: "text-violet-300",
  },
};

export function WorkspacePageHeader({
  eyebrow,
  title,
  description,
  icon: Icon,
  accent = "sky",
  context,
  actions,
  className,
}: {
  eyebrow: string;
  title: string;
  description: string;
  icon: LucideIcon;
  accent?: WorkspaceAccent;
  context?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  const accentStyle = ACCENT_STYLES[accent];

  return (
    <header
      className={cn(
        "relative isolate overflow-hidden rounded-2xl border border-[#245b8f] bg-[#123f73] px-5 py-5 text-white shadow-sm sm:px-6",
        className,
      )}
    >
      <div
        className={cn("pointer-events-none absolute -right-20 -top-24 h-64 w-64", accentStyle.glow)}
        aria-hidden="true"
      />
      <div
        className="pointer-events-none absolute inset-y-0 right-0 w-2/5 bg-[linear-gradient(135deg,transparent,rgba(59,130,246,0.12))]"
        aria-hidden="true"
      />
      <div className="relative flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-start gap-4">
          <span className={cn("flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border", accentStyle.icon)}>
            <Icon className="h-5 w-5" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <p className={cn("text-[11px] font-bold uppercase tracking-[0.18em]", accentStyle.eyebrow)}>
              {eyebrow}
            </p>
            <h1 className="mt-1 text-xl font-semibold tracking-tight text-white sm:text-2xl">
              {title}
            </h1>
            <p className="mt-1.5 max-w-3xl text-sm leading-6 text-slate-200">
              {description}
            </p>
            {context && <div className="mt-3 flex flex-wrap items-center gap-2">{context}</div>}
          </div>
        </div>
        {actions && (
          <div className="relative flex shrink-0 flex-wrap items-center gap-2 lg:justify-end">
            {actions}
          </div>
        )}
      </div>
    </header>
  );
}

export function WorkspaceHeaderContext({
  icon: Icon,
  children,
}: {
  icon?: LucideIcon;
  children: ReactNode;
}) {
  return (
    <span className="inline-flex min-h-7 items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-2.5 py-1 text-xs font-medium text-slate-100">
      {Icon && <Icon className="h-3.5 w-3.5 text-sky-300" aria-hidden="true" />}
      {children}
    </span>
  );
}

export function WorkspaceSummaryStrip({
  children,
  label,
  columns = 4,
}: {
  children: ReactNode;
  label: string;
  columns?: 2 | 3 | 4;
}) {
  return (
    <section
      aria-label={label}
      className={cn(
        "grid overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm sm:grid-cols-2",
        columns === 3 ? "lg:grid-cols-3" : columns === 4 ? "lg:grid-cols-4" : "lg:grid-cols-2",
      )}
    >
      {children}
    </section>
  );
}

export function WorkspaceSummaryItem({
  label,
  value,
  helper,
  icon: Icon,
  tone = "default",
}: {
  label: string;
  value: string | number;
  helper?: string;
  icon: LucideIcon;
  tone?: WorkspaceMetricTone;
}) {
  const toneStyles: Record<WorkspaceMetricTone, { surface: string; icon: string }> = {
    default: { surface: "", icon: "bg-slate-100 text-slate-600" },
    attention: { surface: "bg-amber-50/65", icon: "bg-amber-100 text-amber-700" },
    success: { surface: "bg-emerald-50/55", icon: "bg-emerald-100 text-emerald-700" },
    info: { surface: "bg-blue-50/55", icon: "bg-blue-100 text-blue-700" },
  };
  const style = toneStyles[tone];

  return (
    <div
      className={cn(
        "flex min-w-0 items-center gap-3 border-b border-slate-100 px-4 py-3.5 last:border-b-0 sm:[&:nth-child(odd)]:border-r lg:border-b-0 lg:border-r lg:last:border-r-0",
        style.surface,
      )}
    >
      <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", style.icon)}>
        <Icon className="h-4 w-4" aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</p>
        <div className="mt-0.5 flex min-w-0 items-baseline gap-2">
          <p className="text-lg font-semibold tabular-nums text-slate-950">{value}</p>
          {helper && <p className="truncate text-xs text-slate-500">{helper}</p>}
        </div>
      </div>
    </div>
  );
}

export function WorkspaceToolbar({
  query,
  onQueryChange,
  searchLabel,
  placeholder,
  resultLabel,
  children,
}: {
  query: string;
  onQueryChange: (value: string) => void;
  searchLabel: string;
  placeholder: string;
  resultLabel?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 border-b border-slate-200 bg-slate-50/70 px-4 py-3.5 lg:flex-row lg:items-center lg:justify-between">
      <div className="relative min-w-0 flex-1 lg:max-w-xl">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
          aria-hidden="true"
        />
        <input
          type="search"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          aria-label={searchLabel}
          placeholder={placeholder}
          className="h-10 w-full rounded-lg border border-slate-300 bg-white pl-9 pr-16 text-sm text-slate-900 shadow-sm outline-none placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        />
        {query && (
          <button
            type="button"
            onClick={() => onQueryChange("")}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md px-1.5 py-1 text-xs font-semibold text-slate-500 hover:bg-slate-100 hover:text-slate-900"
            aria-label="Clear search"
          >
            Clear
          </button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {resultLabel && (
          <span className="mr-1 text-xs font-medium text-slate-500" aria-live="polite">
            {resultLabel}
          </span>
        )}
        {children}
      </div>
    </div>
  );
}

export function WorkspaceEmptyState({
  title,
  description,
  action,
  filtered = false,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  filtered?: boolean;
}) {
  return (
    <div className="px-5 py-12 text-center">
      <span className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl bg-slate-100 text-slate-500">
        {filtered ? (
          <Search className="h-5 w-5" aria-hidden="true" />
        ) : (
          <ArrowRight className="h-5 w-5" aria-hidden="true" />
        )}
      </span>
      <h2 className="mt-4 text-base font-semibold text-slate-950">{title}</h2>
      <p className="mx-auto mt-1.5 max-w-lg text-sm leading-6 text-slate-500">{description}</p>
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  );
}

export function WorkspaceErrorNotice({ children }: { children: ReactNode }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}

export function WorkspaceRouteLoading({
  eyebrow,
  title,
  rows = 5,
}: {
  eyebrow: string;
  title: string;
  rows?: number;
}) {
  return (
    <div
      className="flex flex-col gap-5"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <header className="relative isolate overflow-hidden rounded-2xl border border-[#245b8f] bg-[#123f73] px-5 py-5 text-white shadow-sm sm:px-6">
        <div
          className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 bg-[radial-gradient(circle_at_center,rgba(56,189,248,0.2),transparent_68%)]"
          aria-hidden="true"
        />
        <div className="relative flex items-start gap-4">
          <span
            className="h-11 w-11 shrink-0 animate-pulse rounded-xl border border-sky-300/20 bg-sky-300/10 motion-reduce:animate-none"
            aria-hidden="true"
          />
          <div className="min-w-0">
            <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-sky-300">
              {eyebrow}
            </p>
            <h1 className="mt-1 text-xl font-semibold tracking-tight text-white sm:text-2xl">
              {title}
            </h1>
            <p className="mt-1.5 text-sm leading-6 text-slate-200">
              Preparing the latest workspace context…
            </p>
          </div>
        </div>
      </header>

      <section
        className="grid overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm sm:grid-cols-2 lg:grid-cols-4"
        aria-label={`${title} summary loading`}
      >
        {Array.from({ length: 4 }).map((_, index) => (
          <div
            key={index}
            className="flex items-center gap-3 border-b border-slate-100 px-4 py-3.5 last:border-b-0 sm:[&:nth-child(odd)]:border-r lg:border-b-0 lg:border-r lg:last:border-r-0"
          >
            <span
              className="h-9 w-9 shrink-0 animate-pulse rounded-lg bg-slate-100 motion-reduce:animate-none"
              aria-hidden="true"
            />
            <span className="min-w-0 flex-1" aria-hidden="true">
              <span className="block h-2.5 w-20 animate-pulse rounded bg-slate-100 motion-reduce:animate-none" />
              <span className="mt-2 block h-5 w-14 animate-pulse rounded bg-slate-200 motion-reduce:animate-none" />
            </span>
          </div>
        ))}
      </section>

      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        aria-label={`${title} content loading`}
      >
        <div className="border-b border-slate-200 px-4 py-4 sm:px-5">
          <span
            className="block h-3 w-32 animate-pulse rounded bg-slate-100 motion-reduce:animate-none"
            aria-hidden="true"
          />
          <span
            className="mt-2 block h-5 w-56 max-w-full animate-pulse rounded bg-slate-200 motion-reduce:animate-none"
            aria-hidden="true"
          />
        </div>
        <div className="divide-y divide-slate-100 px-4 sm:px-5" aria-hidden="true">
          {Array.from({ length: rows }).map((_, index) => (
            <div key={index} className="flex items-center gap-4 py-4">
              <span className="h-9 w-9 shrink-0 animate-pulse rounded-lg bg-slate-100 motion-reduce:animate-none" />
              <span className="min-w-0 flex-1">
                <span className="block h-3 w-2/5 animate-pulse rounded bg-slate-200 motion-reduce:animate-none" />
                <span className="mt-2 block h-2.5 w-3/5 animate-pulse rounded bg-slate-100 motion-reduce:animate-none" />
              </span>
              <span className="hidden h-8 w-20 animate-pulse rounded-lg bg-slate-100 motion-reduce:animate-none sm:block" />
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
