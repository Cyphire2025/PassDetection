"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils/cn";
import type { MealPlanEntry, MenuCategory } from "../api/menu.api";

export function MealSlot({
  entries,
  icon,
  iconClass,
  categoryById,
  usedDishIds,
  disabled,
  onChange,
}: {
  entries: MealPlanEntry[];
  icon: ReactNode;
  iconClass: string;
  categoryById: ReadonlyMap<string, MenuCategory>;
  usedDishIds: Set<string>;
  disabled: boolean;
  onChange: (entry: MealPlanEntry, dishId: string) => void;
}) {
  const mealType = entries[0]?.meal_type ?? "meal";

  return (
    <div className="flex items-start gap-3 px-4 py-3.5">
      <span
        className={cn(
          "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ring-1",
          iconClass,
        )}
        aria-hidden="true"
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
          {mealType}
        </p>
        <div className="mt-1.5 space-y-2">
          {entries.map((entry) => {
            const category = categoryById.get(entry.category_id ?? "");
            const availableDishes =
              category?.dishes.filter(
                (dish) =>
                  (dish.is_active || dish.id === entry.dish_id) &&
                  (!usedDishIds.has(dish.id) || dish.id === entry.dish_id),
              ) ?? [];
            return (
              <div
                key={entry.id}
                className="rounded-lg border border-slate-100 bg-slate-50/70 px-3 py-2"
              >
                <div className="flex items-center gap-2">
                  <span className="min-w-20 truncate text-[10px] font-semibold uppercase tracking-wide text-blue-600">
                    {entry.category_name}
                  </span>
                  <select
                    value={entry.dish_id ?? ""}
                    onChange={(event) => onChange(entry, event.target.value)}
                    disabled={disabled || availableDishes.length === 0}
                    aria-label={`Change day ${entry.day_number} ${entry.meal_type} ${entry.category_name}`}
                    className="min-w-0 flex-1 cursor-pointer rounded-md border border-transparent bg-white px-2 py-1.5 text-sm font-semibold text-slate-800 outline-none transition hover:border-slate-200 focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {entry.dish_id === null && (
                      <option value="" disabled>
                        {entry.dish_name} (removed from library)
                      </option>
                    )}
                    {availableDishes.map((dish) => (
                      <option key={dish.id} value={dish.id}>
                        {dish.name}
                        {!dish.is_active ? " (paused)" : ""}
                      </option>
                    ))}
                  </select>
                </div>
                {entry.notes && (
                  <p className="mt-1 truncate text-[11px] text-slate-400">
                    {entry.notes}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
