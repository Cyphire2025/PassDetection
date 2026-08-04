import type React from "react";
import { AlertCircle, ArrowRight, Search, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils/cn";

export function OperationsPageHeader({
  eyebrow,
  title,
  description,
  icon: Icon,
  actions,
  context,
  tone = "navy",
}: {
  eyebrow: string;
  title: string;
  description: string;
  icon: LucideIcon;
  actions?: React.ReactNode;
  context?: React.ReactNode;
  tone?: "navy" | "blue";
}) {
  return (
    <header
      className={cn(
        "relative overflow-hidden rounded-2xl border px-5 py-5 text-white shadow-sm sm:px-6",
        tone === "navy"
          ? "border-[#245b8f] bg-[#123f73]"
          : "border-[#2b6ba5] bg-[#16538f]",
      )}
    >
      <div
        className="pointer-events-none absolute inset-y-0 right-0 w-2/5 bg-[linear-gradient(135deg,transparent,rgba(59,130,246,0.16))]"
        aria-hidden="true"
      />
      <div className="relative flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-start gap-4">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-white/15 bg-white/10 text-sky-200">
            <Icon className="h-5 w-5" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-sky-300">
              {eyebrow}
            </p>
            <h1 className="mt-1 text-xl font-semibold tracking-tight text-white sm:text-2xl">
              {title}
            </h1>
            <p className="mt-1.5 max-w-3xl text-sm leading-6 text-slate-300">
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

export function OperationsSummaryStrip({
  children,
  label,
}: {
  children: React.ReactNode;
  label: string;
}) {
  return (
    <section
      aria-label={label}
      className="grid overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm sm:grid-cols-2 lg:grid-cols-4"
    >
      {children}
    </section>
  );
}

export function OperationsSummaryItem({
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
  tone?: "default" | "attention" | "success";
}) {
  return (
    <div
      className={cn(
        "flex min-w-0 items-center gap-3 border-b border-slate-100 px-4 py-3.5 last:border-b-0 sm:[&:nth-child(odd)]:border-r lg:border-b-0 lg:border-r lg:last:border-r-0",
        tone === "attention" && "bg-amber-50/65",
        tone === "success" && "bg-emerald-50/55",
      )}
    >
      <span
        className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
          tone === "attention"
            ? "bg-amber-100 text-amber-700"
            : tone === "success"
              ? "bg-emerald-100 text-emerald-700"
              : "bg-slate-100 text-slate-600",
        )}
      >
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

export function OperationsToolbar({
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
  children?: React.ReactNode;
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
          className="h-10 w-full rounded-lg border border-slate-300 bg-white pl-9 pr-9 text-sm text-slate-900 shadow-sm outline-none placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
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
        {resultLabel && <span className="mr-1 text-xs font-medium text-slate-500" aria-live="polite">{resultLabel}</span>}
        {children}
      </div>
    </div>
  );
}

export function OperationsEmptyState({
  title,
  description,
  action,
  filtered = false,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
  filtered?: boolean;
}) {
  return (
    <div className="px-5 py-12 text-center">
      <span className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl bg-slate-100 text-slate-500">
        {filtered ? <Search className="h-5 w-5" aria-hidden="true" /> : <ArrowRight className="h-5 w-5" aria-hidden="true" />}
      </span>
      <h2 className="mt-4 text-base font-semibold text-slate-950">{title}</h2>
      <p className="mx-auto mt-1.5 max-w-lg text-sm leading-6 text-slate-500">{description}</p>
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  );
}

export function OperationsErrorNotice({ children }: { children: React.ReactNode }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}
