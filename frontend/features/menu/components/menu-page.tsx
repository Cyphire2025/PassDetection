"use client";

import { useState } from "react";
import {
  BookOpen,
  CalendarDays,
  ChefHat,
  Layers3,
  Sparkles,
  UtensilsCrossed,
} from "lucide-react";
import { Card, CardContent, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/shared/page-header";
import { cn } from "@/lib/utils/cn";
import { useMenuWorkspace } from "../hooks/use-menu";
import { MenuLibrary } from "./menu-library";
import { MealPlanner } from "./meal-planner";

type MenuView = "library" | "planner";

export function MenuPage() {
  const [view, setView] = useState<MenuView>("library");
  const { data, isLoading, error } = useMenuWorkspace();

  if (isLoading) {
    return <MenuPageSkeleton />;
  }

  if (error || !data) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          title="Menu"
          description="Build a dish library and create non-repeating trip meal plans."
        />
        <div
          className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-700"
          role="alert"
        >
          Menu data could not be loaded. Please refresh the page and try again.
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Menu"
        description="Keep your dishes in one place and turn them into balanced lunch and dinner plans."
      />

      <Card className="overflow-hidden border-blue-100 bg-gradient-to-br from-blue-50 via-white to-cyan-50">
        <CardContent className="p-5 sm:p-6">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-start gap-4">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white shadow-sm shadow-blue-200">
                <ChefHat className="h-5 w-5" aria-hidden="true" />
              </span>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="font-semibold text-slate-900">
                    Smart, repeat-free planning
                  </h2>
                  <span className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-white/80 px-2 py-0.5 text-[11px] font-medium text-blue-700">
                    <Sparkles className="h-3 w-3" aria-hidden="true" />
                    Balanced automatically
                  </span>
                </div>
                <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600">
                  Select categories such as Chicken, Paneer, Fish, or Dal. Every
                  lunch and dinner gets one unique dish from each selected
                  category.
                </p>
              </div>
            </div>
            <div className="grid shrink-0 grid-cols-3 gap-2 text-center">
              {[
                ["1", "Add dishes"],
                ["2", "Set days"],
                ["3", "Get plan"],
              ].map(([step, label]) => (
                <div
                  key={step}
                  className="min-w-20 rounded-lg border border-white/80 bg-white/70 px-3 py-2 shadow-sm"
                >
                  <div className="text-sm font-bold text-blue-700">{step}</div>
                  <div className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
                    {label}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard
          icon={<Layers3 className="h-4 w-4" />}
          label="Categories"
          value={String(data.categories.length)}
          tone="violet"
        />
        <MetricCard
          icon={<UtensilsCrossed className="h-4 w-4" />}
          label="Active dishes"
          value={String(data.active_dishes)}
          detail={
            data.total_dishes !== data.active_dishes
              ? `${data.total_dishes} total`
              : undefined
          }
          tone="emerald"
        />
        <MetricCard
          icon={<CalendarDays className="h-4 w-4" />}
          label="All-category capacity"
          value={`${data.max_trip_days_without_repeats} day${
            data.max_trip_days_without_repeats === 1 ? "" : "s"
          }`}
          tone="blue"
        />
        <MetricCard
          icon={<BookOpen className="h-4 w-4" />}
          label="Saved plans"
          value={String(data.plans.length)}
          tone="amber"
        />
      </div>

      <div
        className="grid grid-cols-2 rounded-xl border border-slate-200 bg-slate-100 p-1"
        role="tablist"
        aria-label="Menu sections"
      >
        <button
          type="button"
          role="tab"
          aria-selected={view === "library"}
          onClick={() => setView("library")}
          className={cn(
            "flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition",
            view === "library"
              ? "bg-white text-slate-900 shadow-sm"
              : "text-slate-500 hover:text-slate-800",
          )}
        >
          <UtensilsCrossed className="h-4 w-4" aria-hidden="true" />
          Dish Library
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === "planner"}
          onClick={() => setView("planner")}
          className={cn(
            "flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition",
            view === "planner"
              ? "bg-white text-slate-900 shadow-sm"
              : "text-slate-500 hover:text-slate-800",
          )}
        >
          <Sparkles className="h-4 w-4" aria-hidden="true" />
          Meal Planner
        </button>
      </div>

      {view === "library" ? (
        <MenuLibrary categories={data.categories} />
      ) : (
        <MealPlanner
          categories={data.categories}
          plans={data.plans}
          onOpenLibrary={() => setView("library")}
        />
      )}
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail?: string;
  tone: "blue" | "emerald" | "violet" | "amber";
}) {
  const tones = {
    blue: "bg-blue-50 text-blue-600 ring-blue-100",
    emerald: "bg-emerald-50 text-emerald-600 ring-emerald-100",
    violet: "bg-violet-50 text-violet-600 ring-violet-100",
    amber: "bg-amber-50 text-amber-600 ring-amber-100",
  };

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-slate-500">{label}</p>
            <p className="mt-1 truncate text-lg font-bold text-slate-900">{value}</p>
            {detail && <p className="mt-0.5 text-[11px] text-slate-400">{detail}</p>}
          </div>
          <span
            className={cn(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ring-1",
              tones[tone],
            )}
          >
            {icon}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

function MenuPageSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <Skeleton className="h-6 w-28" />
        <Skeleton className="mt-2 h-4 w-96 max-w-full" />
      </div>
      <Skeleton className="h-36 w-full rounded-xl" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-24 rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-12 w-full rounded-xl" />
      <div className="grid gap-4 md:grid-cols-2">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-64 rounded-xl" />
        ))}
      </div>
    </div>
  );
}
