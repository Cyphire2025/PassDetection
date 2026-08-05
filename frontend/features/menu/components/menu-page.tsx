"use client";

import { useState, type KeyboardEvent } from "react";
import dynamic from "next/dynamic";
import {
  BookOpen,
  CalendarDays,
  ChefHat,
  Layers3,
  Sparkles,
  UtensilsCrossed,
} from "lucide-react";
import {
  WorkspaceErrorNotice,
  WorkspaceHeaderContext,
  WorkspacePageHeader,
  WorkspaceSummaryItem,
  WorkspaceSummaryStrip,
} from "@/components/shared/workspace-ui";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils/cn";
import { useMenuWorkspace } from "../hooks/use-menu";

const MenuLibrary = dynamic(
  () => import("./menu-library").then((module) => module.MenuLibrary),
  { loading: () => <MenuWorkspaceLoading /> },
);
const MealPlanner = dynamic(
  () => import("./meal-planner").then((module) => module.MealPlanner),
  { loading: () => <MenuWorkspaceLoading /> },
);

type MenuView = "library" | "planner";

export function MenuPage() {
  const [view, setView] = useState<MenuView>("library");
  const { data, isLoading, error } = useMenuWorkspace();

  if (isLoading) {
    return <MenuPageSkeleton />;
  }

  if (error || !data) {
    return (
      <div className="flex flex-col gap-5">
        <WorkspacePageHeader
          eyebrow="Culinary planning workspace"
          title="Menu"
          description="Build the dish library and generate balanced, non-repeating meal plans for each trip."
          icon={ChefHat}
          accent="amber"
        />
        <WorkspaceErrorNotice>
          Menu data could not be refreshed. Reload the workspace to continue planning.
        </WorkspaceErrorNotice>
      </div>
    );
  }

  const openView = (nextView: MenuView) => {
    setView(nextView);
  };

  const moveTabFocus = (
    event: KeyboardEvent<HTMLButtonElement>,
    nextView: MenuView,
  ) => {
    event.preventDefault();
    preloadMenuView(nextView);
    setView(nextView);
    document.getElementById(
      nextView === "library" ? "menu-library-tab" : "meal-planner-tab",
    )?.focus();
  };

  const handleTabKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    currentView: MenuView,
  ) => {
    if (event.key === "Home") {
      moveTabFocus(event, "library");
      return;
    }
    if (event.key === "End") {
      moveTabFocus(event, "planner");
      return;
    }
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      moveTabFocus(event, currentView === "library" ? "planner" : "library");
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <WorkspacePageHeader
        eyebrow="Culinary planning workspace"
        title="Menu"
        description="Maintain a controlled dish library, understand repeat-free capacity, and turn approved categories into balanced lunch and dinner plans."
        icon={ChefHat}
        accent="amber"
        context={(
          <>
            <WorkspaceHeaderContext icon={Layers3}>
              {data.categories.length.toLocaleString()} categories
            </WorkspaceHeaderContext>
            <WorkspaceHeaderContext icon={BookOpen}>
              {data.plans.length.toLocaleString()} saved plans
            </WorkspaceHeaderContext>
          </>
        )}
        actions={(
          <button
            type="button"
            onClick={() => openView(view === "library" ? "planner" : "library")}
            onMouseEnter={() => preloadMenuView(view === "library" ? "planner" : "library")}
            onFocus={() => preloadMenuView(view === "library" ? "planner" : "library")}
            onPointerDown={() => preloadMenuView(view === "library" ? "planner" : "library")}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-white px-4 text-sm font-semibold text-[#123f73] shadow-sm transition hover:bg-amber-50 active:bg-amber-100"
          >
            {view === "library" ? (
              <>
                <Sparkles className="h-4 w-4" aria-hidden="true" />
                Open Meal Planner
              </>
            ) : (
              <>
                <UtensilsCrossed className="h-4 w-4" aria-hidden="true" />
                Open Dish Library
              </>
            )}
          </button>
        )}
      />

      <WorkspaceSummaryStrip label="Menu planning capacity">
        <WorkspaceSummaryItem
          icon={Layers3}
          label="Categories"
          value={data.categories.length.toLocaleString()}
          helper="dish groups"
        />
        <WorkspaceSummaryItem
          icon={UtensilsCrossed}
          label="Active dishes"
          value={data.active_dishes.toLocaleString()}
          helper={data.total_dishes !== data.active_dishes ? `${data.total_dishes} total` : "available now"}
          tone="success"
        />
        <WorkspaceSummaryItem
          icon={CalendarDays}
          label="Repeat-free capacity"
          value={`${data.max_trip_days_without_repeats} day${data.max_trip_days_without_repeats === 1 ? "" : "s"}`}
          helper="all categories"
          tone="info"
        />
        <WorkspaceSummaryItem
          icon={BookOpen}
          label="Saved plans"
          value={data.plans.length.toLocaleString()}
          helper="trip menus"
        />
      </WorkspaceSummaryStrip>

      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        aria-labelledby="menu-workflow-heading"
      >
        <div className="flex flex-col gap-4 border-b border-slate-200 bg-slate-50/70 px-4 py-3.5 lg:flex-row lg:items-center lg:justify-between sm:px-5">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              Repeat-free workflow
            </p>
            <h2 id="menu-workflow-heading" className="mt-0.5 font-semibold text-slate-950">
              Build once, plan with confidence
            </h2>
          </div>
          <ol className="grid grid-cols-3 gap-2 text-center">
            {[
              ["1", "Add dishes"],
              ["2", "Set trip days"],
              ["3", "Generate plan"],
            ].map(([step, label]) => (
              <li
                key={step}
                className="min-w-20 rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-sm"
              >
                <span className="block text-sm font-bold text-amber-700">{step}</span>
                <span className="block text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                  {label}
                </span>
              </li>
            ))}
          </ol>
        </div>

        <div
          className="grid grid-cols-2 border-b border-slate-200 bg-slate-100 p-1"
          role="tablist"
          aria-label="Menu sections"
        >
          <button
            id="menu-library-tab"
            type="button"
            role="tab"
            aria-selected={view === "library"}
            aria-controls="menu-library-panel"
            tabIndex={view === "library" ? 0 : -1}
            onClick={() => openView("library")}
            onKeyDown={(event) => handleTabKeyDown(event, "library")}
            onMouseEnter={() => preloadMenuView("library")}
            onFocus={() => preloadMenuView("library")}
            onPointerDown={() => preloadMenuView("library")}
            className={cn(
              "flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition",
              view === "library"
                ? "bg-white text-slate-950 shadow-sm"
                : "text-slate-600 hover:bg-white/60 hover:text-slate-900",
            )}
          >
            <UtensilsCrossed className="h-4 w-4" aria-hidden="true" />
            Dish Library
          </button>
          <button
            id="meal-planner-tab"
            type="button"
            role="tab"
            aria-selected={view === "planner"}
            aria-controls="meal-planner-panel"
            tabIndex={view === "planner" ? 0 : -1}
            onClick={() => openView("planner")}
            onKeyDown={(event) => handleTabKeyDown(event, "planner")}
            onMouseEnter={() => preloadMenuView("planner")}
            onFocus={() => preloadMenuView("planner")}
            onPointerDown={() => preloadMenuView("planner")}
            className={cn(
              "flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition",
              view === "planner"
                ? "bg-white text-slate-950 shadow-sm"
                : "text-slate-600 hover:bg-white/60 hover:text-slate-900",
            )}
          >
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            Meal Planner
          </button>
        </div>

        <div className="p-4 sm:p-5">
          {view === "library" ? (
            <div
              id="menu-library-panel"
              role="tabpanel"
              aria-labelledby="menu-library-tab"
              tabIndex={0}
            >
              <MenuLibrary categories={data.categories} />
            </div>
          ) : (
            <div
              id="meal-planner-panel"
              role="tabpanel"
              aria-labelledby="meal-planner-tab"
              tabIndex={0}
            >
              <MealPlanner
                categories={data.categories}
                plans={data.plans}
                onOpenLibrary={() => openView("library")}
              />
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function preloadMenuView(view: MenuView) {
  if (view === "library") {
    void import("./menu-library");
    return;
  }
  void import("./meal-planner");
}

function MenuWorkspaceLoading() {
  return (
    <div
      className="grid gap-4 md:grid-cols-[minmax(14rem,0.7fr)_minmax(0,1.3fr)]"
      role="status"
      aria-live="polite"
      aria-label="Loading menu workspace"
    >
      <Skeleton className="h-72 rounded-xl" />
      <Skeleton className="h-72 rounded-xl" />
    </div>
  );
}

function MenuPageSkeleton() {
  return (
    <div
      className="flex flex-col gap-5"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label="Loading menu planning workspace"
    >
      <WorkspacePageHeader
        eyebrow="Culinary planning workspace"
        title="Menu"
        description="Loading the dish library, repeat-free capacity, and saved trip plans."
        icon={ChefHat}
        accent="amber"
      />
      <WorkspaceSummaryStrip label="Loading menu planning capacity">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-[72px] rounded-none" />
        ))}
      </WorkspaceSummaryStrip>
      <Skeleton className="h-14 w-full rounded-xl" />
      <div className="grid gap-4 md:grid-cols-2">
        <Skeleton className="h-72 rounded-xl" />
        <Skeleton className="h-72 rounded-xl" />
      </div>
    </div>
  );
}
