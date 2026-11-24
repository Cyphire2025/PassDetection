"use client";

import { AlertCircle, BookOpen, CalendarDays, Check, Sparkles } from "lucide-react";
import { Button, Card, CardContent, ConfirmDialog } from "@/components/ui";
import { EmptyState } from "@/components/shared/empty-state";
import { cn } from "@/lib/utils/cn";
import type { MealPlan, MenuCategory } from "../api/menu.api";
import { useMealPlanner } from "../hooks/use-meal-planner";
import { GeneratePlanDialog } from "./generate-plan-dialog";
import { PlanDetails } from "./meal-plan-details";

export function MealPlanner({ categories, plans, onOpenLibrary }: {
  categories: MenuCategory[];
  plans: MealPlan[];
  onOpenLibrary: () => void;
}) {
  const planner = useMealPlanner(categories, plans);

  return (
    <section className="space-y-5" aria-labelledby="meal-planner-title">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">
            Step 2
          </p>
          <h2 id="meal-planner-title" className="mt-1 text-base font-semibold text-slate-900">
            Create a trip meal plan
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            Every lunch and dinner gets one unique dish from every category you
            select.
          </p>
        </div>
        <Button
          type="button"
          leftIcon={<Sparkles className="h-4 w-4" />}
          onClick={planner.openGenerator}
          disabled={!planner.hasPlannableCategory}
        >
          Generate Meal Plan
        </Button>
      </div>

      {planner.feedback && (
        <div
          className={cn(
            "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm",
            planner.feedback.kind === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-red-200 bg-red-50 text-red-700",
          )}
          role={planner.feedback.kind === "error" ? "alert" : "status"}
        >
          {planner.feedback.kind === "success" ? (
            <Check className="h-4 w-4 shrink-0" aria-hidden="true" />
          ) : (
            <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
          )}
          {planner.feedback.message}
        </div>
      )}

      {!planner.hasPlannableCategory && (
        <div className="flex flex-col gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-2">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <p>
              Add at least two active dishes to one category before creating a
              one-day lunch and dinner plan.
            </p>
          </div>
          <Button type="button" size="sm" variant="secondary" onClick={onOpenLibrary}>
            Open Dish Library
          </Button>
        </div>
      )}

      {plans.length === 0 ? (
        <EmptyState
          icon={<BookOpen className="h-5 w-5" />}
          title="No meal plans yet"
          description={
            planner.hasPlannableCategory
              ? "Choose your categories and every meal will include one dish from each."
              : "Build your dish library first, then come back here to create a plan."
          }
          action={
            planner.hasPlannableCategory
              ? { label: "Generate first plan", onClick: planner.openGenerator }
              : { label: "Add dishes", onClick: onOpenLibrary }
          }
          className="bg-white"
        />
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-[250px_minmax(0,1fr)]">
          <Card className="overflow-hidden">
            <CardContent className="p-0">
              <div className="border-b border-slate-100 px-4 py-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Saved plans
                </p>
              </div>
              <div className="max-h-[560px] space-y-1 overflow-y-auto p-2">
                {plans.map((plan) => {
                  const active = planner.selectedPlan?.id === plan.id;
                  return (
                    <button
                      key={plan.id}
                      type="button"
                      onClick={() => planner.selectPlan(plan.id)}
                      className={cn(
                        "w-full rounded-lg border px-3 py-3 text-left transition",
                        active
                          ? "border-blue-200 bg-blue-50"
                          : "border-transparent hover:border-slate-200 hover:bg-slate-50",
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p
                          className={cn(
                            "line-clamp-2 text-sm font-semibold",
                            active ? "text-blue-900" : "text-slate-800",
                          )}
                        >
                          {plan.name}
                        </p>
                        {active && (
                          <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-blue-600" />
                        )}
                      </div>
                      <div className="mt-2 flex items-center gap-3 text-[11px] text-slate-500">
                        <span className="inline-flex items-center gap-1">
                          <CalendarDays className="h-3 w-3" />
                          {plan.trip_days} days
                        </span>
                        <span>{plan.trip_days * 2} meals</span>
                        <span>{plan.unique_dish_count} dishes</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </CardContent>
          </Card>

          {planner.details && <PlanDetails {...planner.details} />}
        </div>
      )}

      <GeneratePlanDialog {...planner.generator} />

      <ConfirmDialog
        isOpen={planner.deletion.plan !== null}
        title="Delete meal plan?"
        description={`${planner.deletion.plan?.name ?? "This plan"} will be permanently removed. Your dish library will not be affected.`}
        confirmLabel="Delete plan"
        variant="danger"
        isLoading={planner.deletion.isPending}
        onConfirm={() => void planner.deletion.confirm()}
        onClose={() => planner.deletion.close()}
      />
    </section>
  );
}
