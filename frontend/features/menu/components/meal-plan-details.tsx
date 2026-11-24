"use client";

import { type FormEvent, useMemo } from "react";
import { CalendarDays, Clock3, Copy, FileSpreadsheet, Moon, Pencil, RefreshCw, Sun, Trash2, UtensilsCrossed } from "lucide-react";
import { Badge, Button, Card, CardContent, Input } from "@/components/ui";
import type { MealPlan, MealPlanEntry, MenuCategory } from "../api/menu.api";
import type { EditingMealPlan } from "../types/meal-planner";
import { formatDate } from "../utils/meal-plan-format";
import { MealSlot } from "./meal-plan-slot";

export function PlanDetails({
  plan,
  categories,
  editingPlan,
  setEditingPlan,
  onSavePlanDetails,
  onRegenerate,
  onCopy,
  onExport,
  onDelete,
  onReplaceMeal,
  isRegenerating,
  isExporting,
  isUpdatingEntry,
  isUpdatingPlan,
}: {
  plan: MealPlan;
  categories: MenuCategory[];
  editingPlan: EditingMealPlan | null;
  setEditingPlan: (
    value: EditingMealPlan | null,
  ) => void;
  onSavePlanDetails: (event: FormEvent) => void;
  onRegenerate: () => void;
  onCopy: () => void;
  onExport: () => void;
  onDelete: () => void;
  onReplaceMeal: (entry: MealPlanEntry, dishId: string) => void;
  isRegenerating: boolean;
  isExporting: boolean;
  isUpdatingEntry: boolean;
  isUpdatingPlan: boolean;
}) {
  const usedDishIds = useMemo(() => new Set(
    plan.days
      .flatMap((day) => [...day.lunch, ...day.dinner])
      .map((entry) => entry.dish_id)
      .filter((dishId): dishId is string => dishId !== null),
  ), [plan.days]);
  const categoryById = useMemo(
    () => new Map(categories.map((category) => [category.id, category])),
    [categories],
  );
  const isEditing = editingPlan?.id === plan.id;

  return (
    <Card className="overflow-hidden">
      <CardContent className="p-0">
        <div className="border-b border-slate-100 bg-slate-50/60 p-4 sm:p-5">
          {isEditing ? (
            <form onSubmit={onSavePlanDetails} className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Input
                  label="Plan name"
                  value={editingPlan.name}
                  onChange={(event) =>
                    setEditingPlan({
                      ...editingPlan,
                      name: event.target.value,
                    })
                  }
                  autoFocus
                  maxLength={150}
                />
                <Input
                  type="date"
                  label="Trip start date (optional)"
                  value={editingPlan.startDate}
                  onChange={(event) =>
                    setEditingPlan({
                      ...editingPlan,
                      startDate: event.target.value,
                    })
                  }
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setEditingPlan(null)}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  size="sm"
                  isLoading={isUpdatingPlan}
                  disabled={!editingPlan.name.trim()}
                >
                  Save details
                </Button>
              </div>
            </form>
          ) : (
            <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-lg font-bold text-slate-900">{plan.name}</h3>
                  <Badge variant="success" dot>
                    No repeats
                  </Badge>
                </div>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                  <span className="inline-flex items-center gap-1.5">
                    <CalendarDays className="h-3.5 w-3.5" />
                    {plan.trip_days} day{plan.trip_days === 1 ? "" : "s"}
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <UtensilsCrossed className="h-3.5 w-3.5" />
                    {plan.unique_dish_count} unique dishes
                  </span>
                  {plan.start_date && (
                    <span className="inline-flex items-center gap-1.5">
                      <Clock3 className="h-3.5 w-3.5" />
                      Starts {formatDate(plan.start_date, false)}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  leftIcon={<Pencil className="h-3.5 w-3.5" />}
                  onClick={() =>
                    setEditingPlan({
                      id: plan.id,
                      name: plan.name,
                      startDate: plan.start_date ?? "",
                    })
                  }
                >
                  Edit
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  leftIcon={<Copy className="h-3.5 w-3.5" />}
                  onClick={onCopy}
                >
                  Copy
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  leftIcon={<FileSpreadsheet className="h-3.5 w-3.5" />}
                  onClick={onExport}
                  isLoading={isExporting}
                >
                  Excel
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  leftIcon={<RefreshCw className="h-3.5 w-3.5" />}
                  onClick={onRegenerate}
                  isLoading={isRegenerating}
                >
                  Regenerate
                </Button>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 text-slate-400 hover:bg-red-50 hover:text-red-600"
                  onClick={onDelete}
                  aria-label={`Delete ${plan.name}`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          )}
        </div>

        <div className="grid gap-3 p-4 sm:p-5 md:grid-cols-2">
          {plan.days.map((day) => (
            <article
              key={day.day_number}
              className="overflow-hidden rounded-xl border border-slate-200 bg-white"
            >
              <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-4 py-2.5">
                <div>
                  <p className="text-xs font-bold uppercase tracking-wide text-slate-700">
                    Day {day.day_number}
                  </p>
                  {day.date && (
                    <p className="mt-0.5 text-[11px] text-slate-400">
                      {formatDate(day.date, true)}
                    </p>
                  )}
                </div>
                <span className="text-[10px] font-medium text-slate-400">
                  2 meals · {day.lunch.length + day.dinner.length} dishes
                </span>
              </div>
              <div className="divide-y divide-slate-100">
                <MealSlot
                  entries={day.lunch}
                  icon={<Sun className="h-4 w-4" />}
                  iconClass="bg-amber-50 text-amber-600 ring-amber-100"
                  categoryById={categoryById}
                  usedDishIds={usedDishIds}
                  disabled={isUpdatingEntry}
                  onChange={onReplaceMeal}
                />
                <MealSlot
                  entries={day.dinner}
                  icon={<Moon className="h-4 w-4" />}
                  iconClass="bg-indigo-50 text-indigo-600 ring-indigo-100"
                  categoryById={categoryById}
                  usedDishIds={usedDishIds}
                  disabled={isUpdatingEntry}
                  onChange={onReplaceMeal}
                />
              </div>
            </article>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
