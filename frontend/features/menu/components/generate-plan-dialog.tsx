"use client";

import { type FormEvent, useRef } from "react";
import { AlertCircle, Check, Sparkles, X } from "lucide-react";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { Button, Input } from "@/components/ui";
import { cn } from "@/lib/utils/cn";
import type { MenuCategory } from "../api/menu.api";

export function GeneratePlanDialog({
  isOpen,
  categories,
  planName,
  tripDays,
  startDate,
  selectedCategoryIds,
  selectedActiveDishCount,
  requiredDishesPerCategory,
  requiredDishCount,
  missingDishCount,
  categoryShortages,
  isGenerating,
  onPlanNameChange,
  onTripDaysChange,
  onStartDateChange,
  onToggleCategory,
  onSubmit,
  onClose,
}: {
  isOpen: boolean;
  categories: MenuCategory[];
  planName: string;
  tripDays: number;
  startDate: string;
  selectedCategoryIds: string[];
  selectedActiveDishCount: number;
  requiredDishesPerCategory: number;
  requiredDishCount: number;
  missingDishCount: number;
  categoryShortages: { id: string; name: string; missing: number }[];
  isGenerating: boolean;
  onPlanNameChange: (value: string) => void;
  onTripDaysChange: (value: number) => void;
  onStartDateChange: (value: string) => void;
  onToggleCategory: (categoryId: string) => void;
  onSubmit: (event: FormEvent) => void;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen, canClose: !isGenerating, onClose });
  if (!isOpen) return null;

  return (
    <div ref={dialogRef} onKeyDown={handleKeyDown} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <form
        onSubmit={onSubmit}
        className="max-h-[calc(100vh-2rem)] w-full max-w-xl overflow-y-auto rounded-xl bg-white shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="generate-plan-title"
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4 sm:px-6">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600 ring-1 ring-blue-100">
              <Sparkles className="h-4 w-4" aria-hidden="true" />
            </span>
            <div>
              <h2 id="generate-plan-title" className="text-lg font-semibold text-slate-900">
                Generate meal plan
              </h2>
              <p className="mt-1 text-sm leading-5 text-slate-500">
                Every selected category adds one unique dish to each lunch and
                dinner.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
            aria-label="Close generator"
            disabled={isGenerating}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-5 px-5 py-5 sm:px-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Input
                label="Plan name"
                value={planName}
                onChange={(event) => onPlanNameChange(event.target.value)}
                placeholder="e.g. Singapore Group – October"
                maxLength={150}
                data-dialog-initial-focus
                required
              />
            </div>
            <Input
              type="number"
              label="Number of trip days"
              min={1}
              max={60}
              value={tripDays}
              onChange={(event) =>
                onTripDaysChange(
                  Math.min(60, Math.max(1, Number(event.target.value) || 1)),
                )
              }
              hint={`${requiredDishesPerCategory} active dishes needed in each selected category`}
              required
            />
            <Input
              type="date"
              label="Trip start date (optional)"
              value={startDate}
              onChange={(event) => onStartDateChange(event.target.value)}
              hint="Adds dates beside Day 1, Day 2, etc."
            />
          </div>

          <div>
            <div className="flex items-center justify-between gap-3">
              <label className="text-sm font-medium text-slate-700">
                Categories to use
              </label>
              <span className="text-xs text-slate-400">
                {selectedActiveDishCount} active dishes
              </span>
            </div>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {categories.map((category) => {
                const checked = selectedCategoryIds.includes(category.id);
                const disabled = category.active_dish_count === 0;
                return (
                  <label
                    key={category.id}
                    className={cn(
                      "flex cursor-pointer items-center justify-between gap-3 rounded-lg border px-3 py-2.5 transition",
                      checked
                        ? "border-blue-300 bg-blue-50"
                        : "border-slate-200 bg-white hover:bg-slate-50",
                      disabled && "cursor-not-allowed opacity-50",
                    )}
                  >
                    <span className="flex items-center gap-2.5">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={() => onToggleCategory(category.id)}
                        className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                      />
                      <span className="text-sm font-medium text-slate-700">
                        {category.name}
                      </span>
                    </span>
                    <span className="text-xs text-slate-400">
                      {category.active_dish_count}/{requiredDishesPerCategory}
                    </span>
                  </label>
                );
              })}
            </div>
          </div>

          <div
            className={cn(
              "rounded-xl border p-4",
              missingDishCount === 0 && selectedCategoryIds.length > 0
                ? "border-emerald-200 bg-emerald-50"
                : "border-amber-200 bg-amber-50",
            )}
          >
            <div className="flex items-start gap-3">
              <span
                className={cn(
                  "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
                  missingDishCount === 0 && selectedCategoryIds.length > 0
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-amber-100 text-amber-700",
                )}
              >
                {missingDishCount === 0 && selectedCategoryIds.length > 0 ? (
                  <Check className="h-4 w-4" />
                ) : (
                  <AlertCircle className="h-4 w-4" />
                )}
              </span>
              <div>
                <p
                  className={cn(
                    "text-sm font-semibold",
                    missingDishCount === 0 && selectedCategoryIds.length > 0
                      ? "text-emerald-800"
                      : "text-amber-800",
                  )}
                >
                  {selectedCategoryIds.length === 0
                    ? "Select at least one category"
                    : categoryShortages.length > 0
                      ? `${categoryShortages.length} selected categor${
                          categoryShortages.length === 1 ? "y needs" : "ies need"
                        } more dishes`
                      : "Ready to create a no-repeat plan"}
                </p>
                <p
                  className={cn(
                    "mt-0.5 text-xs",
                    missingDishCount === 0 && selectedCategoryIds.length > 0
                      ? "text-emerald-700"
                      : "text-amber-700",
                  )}
                >
                  {categoryShortages.length > 0
                    ? categoryShortages
                        .map(
                          (shortage) =>
                            `${shortage.name}: add ${shortage.missing}`,
                        )
                        .join(" · ")
                    : `${selectedCategoryIds.length} categories × ${requiredDishesPerCategory} meal slots = ${requiredDishCount} unique dishes.`}
                </p>
                <p className="mt-1 text-[11px] text-slate-500">
                  {selectedActiveDishCount} active dishes across the selected
                  categories.
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-3 border-t border-slate-100 px-5 py-4 sm:px-6">
          <Button
            type="button"
            variant="secondary"
            onClick={onClose}
            disabled={isGenerating}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            leftIcon={<Sparkles className="h-4 w-4" />}
            isLoading={isGenerating}
            disabled={
              !planName.trim() ||
              selectedCategoryIds.length === 0 ||
              missingDishCount > 0
            }
          >
            Generate plan
          </Button>
        </div>
      </form>
    </div>
  );
}
