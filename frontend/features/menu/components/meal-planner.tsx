"use client";

import { FormEvent, useMemo, useState } from "react";
import {
  AlertCircle,
  BookOpen,
  CalendarDays,
  Check,
  Clock3,
  Copy,
  FileSpreadsheet,
  Moon,
  Pencil,
  RefreshCw,
  Sparkles,
  Sun,
  Trash2,
  UtensilsCrossed,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  ConfirmDialog,
  Input,
} from "@/components/ui";
import { EmptyState } from "@/components/shared/empty-state";
import { copyTextToClipboard } from "@/lib/utils/clipboard";
import { cn } from "@/lib/utils/cn";
import type {
  MealPlan,
  MealPlanEntry,
  MenuCategory,
} from "../api/menu.api";
import {
  useDeleteMealPlan,
  useExportMealPlan,
  useGenerateMealPlan,
  useRegenerateMealPlan,
  useUpdateMealPlan,
  useUpdateMealPlanEntry,
} from "../hooks/use-menu";
import { menuErrorMessage } from "../utils/menu-errors";

type Feedback = { kind: "success" | "error"; message: string } | null;

export function MealPlanner({
  categories,
  plans,
  onOpenLibrary,
}: {
  categories: MenuCategory[];
  plans: MealPlan[];
  onOpenLibrary: () => void;
}) {
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(
    plans[0]?.id ?? null,
  );
  const [generatorOpen, setGeneratorOpen] = useState(false);
  const [planName, setPlanName] = useState("Trip Meal Plan");
  const [tripDays, setTripDays] = useState(suggestedTripDays(categories));
  const [startDate, setStartDate] = useState("");
  const [selectedCategoryIds, setSelectedCategoryIds] = useState<string[]>(
    categories
      .filter((category) => category.active_dish_count > 0)
      .map((category) => category.id),
  );
  const [deletePlan, setDeletePlan] = useState<MealPlan | null>(null);
  const [editingPlan, setEditingPlan] = useState<{
    id: string;
    name: string;
    startDate: string;
  } | null>(null);
  const [feedback, setFeedback] = useState<Feedback>(null);

  const generatePlan = useGenerateMealPlan();
  const regeneratePlan = useRegenerateMealPlan();
  const updatePlan = useUpdateMealPlan();
  const updateEntry = useUpdateMealPlanEntry();
  const deleteMealPlan = useDeleteMealPlan();
  const exportMealPlan = useExportMealPlan();

  const selectedPlan =
    plans.find((plan) => plan.id === selectedPlanId) ?? plans[0] ?? null;
  const selectedCategories = useMemo(
    () =>
      categories.filter((category) =>
        selectedCategoryIds.includes(category.id),
      ),
    [categories, selectedCategoryIds],
  );
  const requiredDishesPerCategory = tripDays * 2;
  const requiredDishCount =
    requiredDishesPerCategory * selectedCategories.length;
  const selectedActiveDishCount = selectedCategories.reduce(
    (total, category) => total + category.active_dish_count,
    0,
  );
  const categoryShortages = selectedCategories
    .filter(
      (category) => category.active_dish_count < requiredDishesPerCategory,
    )
    .map((category) => ({
      id: category.id,
      name: category.name,
      missing: requiredDishesPerCategory - category.active_dish_count,
    }));
  const missingDishCount = categoryShortages.reduce(
    (total, shortage) => total + shortage.missing,
    0,
  );
  const hasPlannableCategory = categories.some(
    (category) => category.active_dish_count >= 2,
  );

  const openGenerator = () => {
    const availableCategoryRecords = categories
      .filter((category) => category.active_dish_count > 0)
    const availableCategories = availableCategoryRecords.map(
      (category) => category.id,
    );
    setSelectedCategoryIds(availableCategories);
    setTripDays(suggestedTripDays(availableCategoryRecords));
    setPlanName("Trip Meal Plan");
    setStartDate("");
    setFeedback(null);
    setGeneratorOpen(true);
  };

  const submitGeneration = async (event: FormEvent) => {
    event.preventDefault();
    if (
      !planName.trim() ||
      selectedCategoryIds.length === 0 ||
      categoryShortages.length > 0
    ) {
      return;
    }
    setFeedback(null);
    try {
      const plan = await generatePlan.mutateAsync({
        name: planName.trim(),
        trip_days: tripDays,
        start_date: startDate || null,
        category_ids: selectedCategoryIds,
      });
      setSelectedPlanId(plan.id);
      setGeneratorOpen(false);
      setFeedback({
        kind: "success",
        message: `${plan.name} created with ${plan.unique_dish_count} unique dishes.`,
      });
    } catch (error) {
      setFeedback({
        kind: "error",
        message: menuErrorMessage(error, "Meal plan could not be generated."),
      });
    }
  };

  const regenerate = async (plan: MealPlan) => {
    setFeedback(null);
    const availableCategoryIds = plan.selected_category_ids.filter((categoryId) =>
      categories.some((category) => category.id === categoryId),
    );
    try {
      await regeneratePlan.mutateAsync({
        planId: plan.id,
        categoryIds:
          availableCategoryIds.length > 0 ? availableCategoryIds : undefined,
      });
      setFeedback({
        kind: "success",
        message: `${plan.name} was rearranged with no repeated dishes.`,
      });
    } catch (error) {
      setFeedback({
        kind: "error",
        message: menuErrorMessage(error, "Meal plan could not be regenerated."),
      });
    }
  };

  const replaceMeal = async (entry: MealPlanEntry, dishId: string) => {
    if (!selectedPlan || !dishId || dishId === entry.dish_id) return;
    setFeedback(null);
    try {
      await updateEntry.mutateAsync({
        planId: selectedPlan.id,
        entryId: entry.id,
        dishId,
      });
      setFeedback({
        kind: "success",
        message: `Day ${entry.day_number} ${entry.meal_type} updated.`,
      });
    } catch (error) {
      setFeedback({
        kind: "error",
        message: menuErrorMessage(error, "The meal could not be changed."),
      });
    }
  };

  const savePlanDetails = async (event: FormEvent) => {
    event.preventDefault();
    if (!editingPlan?.name.trim()) return;
    setFeedback(null);
    try {
      await updatePlan.mutateAsync({
        planId: editingPlan.id,
        name: editingPlan.name.trim(),
        startDate: editingPlan.startDate || null,
      });
      setEditingPlan(null);
      setFeedback({ kind: "success", message: "Plan details updated." });
    } catch (error) {
      setFeedback({
        kind: "error",
        message: menuErrorMessage(error, "Plan details could not be updated."),
      });
    }
  };

  const confirmPlanDelete = async () => {
    if (!deletePlan) return;
    const deletingId = deletePlan.id;
    setFeedback(null);
    try {
      await deleteMealPlan.mutateAsync(deletingId);
      const nextPlan = plans.find((plan) => plan.id !== deletingId);
      setSelectedPlanId(nextPlan?.id ?? null);
      setDeletePlan(null);
      setFeedback({ kind: "success", message: "Meal plan deleted." });
    } catch (error) {
      setFeedback({
        kind: "error",
        message: menuErrorMessage(error, "Meal plan could not be deleted."),
      });
    }
  };

  const copyPlan = async (plan: MealPlan) => {
    setFeedback(null);
    try {
      await copyTextToClipboard(mealPlanAsText(plan));
      setFeedback({
        kind: "success",
        message: "Meal plan copied to the clipboard.",
      });
    } catch {
      setFeedback({
        kind: "error",
        message: "The meal plan could not be copied.",
      });
    }
  };

  const exportPlan = async (plan: MealPlan) => {
    setFeedback(null);
    try {
      await exportMealPlan.mutateAsync({
        planId: plan.id,
        planName: plan.name,
      });
      setFeedback({
        kind: "success",
        message: `${plan.name} exported to Excel.`,
      });
    } catch (error) {
      setFeedback({
        kind: "error",
        message: menuErrorMessage(error, "The Excel file could not be exported."),
      });
    }
  };

  const toggleCategory = (categoryId: string) => {
    setSelectedCategoryIds((current) =>
      current.includes(categoryId)
        ? current.filter((id) => id !== categoryId)
        : [...current, categoryId],
    );
  };

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
          onClick={openGenerator}
          disabled={!hasPlannableCategory}
        >
          Generate Meal Plan
        </Button>
      </div>

      {feedback && (
        <div
          className={cn(
            "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm",
            feedback.kind === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-red-200 bg-red-50 text-red-700",
          )}
          role={feedback.kind === "error" ? "alert" : "status"}
        >
          {feedback.kind === "success" ? (
            <Check className="h-4 w-4 shrink-0" aria-hidden="true" />
          ) : (
            <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
          )}
          {feedback.message}
        </div>
      )}

      {!hasPlannableCategory && (
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
            hasPlannableCategory
              ? "Choose your categories and every meal will include one dish from each."
              : "Build your dish library first, then come back here to create a plan."
          }
          action={
            hasPlannableCategory
              ? { label: "Generate first plan", onClick: openGenerator }
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
                  const active = selectedPlan?.id === plan.id;
                  return (
                    <button
                      key={plan.id}
                      type="button"
                      onClick={() => setSelectedPlanId(plan.id)}
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

          {selectedPlan && (
            <PlanDetails
              plan={selectedPlan}
              categories={categories}
              editingPlan={editingPlan}
              setEditingPlan={setEditingPlan}
              onSavePlanDetails={savePlanDetails}
              onRegenerate={() => void regenerate(selectedPlan)}
              onCopy={() => void copyPlan(selectedPlan)}
              onExport={() => void exportPlan(selectedPlan)}
              onDelete={() => setDeletePlan(selectedPlan)}
              onReplaceMeal={replaceMeal}
              isRegenerating={regeneratePlan.isPending}
              isExporting={exportMealPlan.isPending}
              isUpdatingEntry={updateEntry.isPending}
              isUpdatingPlan={updatePlan.isPending}
            />
          )}
        </div>
      )}

      <GeneratePlanDialog
        isOpen={generatorOpen}
        categories={categories}
        planName={planName}
        tripDays={tripDays}
        startDate={startDate}
        selectedCategoryIds={selectedCategoryIds}
        selectedActiveDishCount={selectedActiveDishCount}
        requiredDishesPerCategory={requiredDishesPerCategory}
        requiredDishCount={requiredDishCount}
        missingDishCount={missingDishCount}
        categoryShortages={categoryShortages}
        isGenerating={generatePlan.isPending}
        onPlanNameChange={setPlanName}
        onTripDaysChange={setTripDays}
        onStartDateChange={setStartDate}
        onToggleCategory={toggleCategory}
        onSubmit={submitGeneration}
        onClose={() => setGeneratorOpen(false)}
      />

      <ConfirmDialog
        isOpen={deletePlan !== null}
        title="Delete meal plan?"
        description={`${deletePlan?.name ?? "This plan"} will be permanently removed. Your dish library will not be affected.`}
        confirmLabel="Delete plan"
        variant="danger"
        isLoading={deleteMealPlan.isPending}
        onConfirm={() => void confirmPlanDelete()}
        onClose={() => setDeletePlan(null)}
      />
    </section>
  );
}

function PlanDetails({
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
  editingPlan: { id: string; name: string; startDate: string } | null;
  setEditingPlan: (
    value: { id: string; name: string; startDate: string } | null,
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
  const usedDishIds = new Set(
    plan.days
      .flatMap((day) => [...day.lunch, ...day.dinner])
      .map((entry) => entry.dish_id)
      .filter((dishId): dishId is string => dishId !== null),
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
                  categories={categories}
                  usedDishIds={usedDishIds}
                  disabled={isUpdatingEntry}
                  onChange={onReplaceMeal}
                />
                <MealSlot
                  entries={day.dinner}
                  icon={<Moon className="h-4 w-4" />}
                  iconClass="bg-indigo-50 text-indigo-600 ring-indigo-100"
                  categories={categories}
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

function MealSlot({
  entries,
  icon,
  iconClass,
  categories,
  usedDishIds,
  disabled,
  onChange,
}: {
  entries: MealPlanEntry[];
  icon: React.ReactNode;
  iconClass: string;
  categories: MenuCategory[];
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
            const category = categories.find(
              (item) => item.id === entry.category_id,
            );
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

function GeneratePlanDialog({
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
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
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
                autoFocus
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

function formatDate(value: string, includeWeekday: boolean): string {
  const date = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: includeWeekday ? undefined : "numeric",
    weekday: includeWeekday ? "short" : undefined,
  }).format(date);
}

function suggestedTripDays(categories: MenuCategory[]): number {
  const activeCounts = categories
    .filter((category) => category.active_dish_count > 0)
    .map((category) => category.active_dish_count);
  if (activeCounts.length === 0) return 1;
  return Math.max(1, Math.min(5, Math.floor(Math.min(...activeCounts) / 2)));
}

function mealPlanAsText(plan: MealPlan): string {
  const lines = [
    plan.name,
    `${plan.trip_days}-day meal plan · Every selected category in every meal · No repeated dishes`,
    "",
  ];
  for (const day of plan.days) {
    lines.push(
      `Day ${day.day_number}${day.date ? ` · ${formatDate(day.date, true)}` : ""}`,
      "Lunch:",
      ...day.lunch.map(
        (entry) => `  ${entry.category_name}: ${entry.dish_name}`,
      ),
      "Dinner:",
      ...day.dinner.map(
        (entry) => `  ${entry.category_name}: ${entry.dish_name}`,
      ),
      "",
    );
  }
  return lines.join("\n").trim();
}
