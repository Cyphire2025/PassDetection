"use client";

import { type FormEvent, useMemo, useState } from "react";
import { copyTextToClipboard } from "@/lib/utils/clipboard";
import { isDownloadCancelled } from "@/lib/api/download-destination";
import type { MealPlan, MealPlanEntry, MenuCategory } from "../api/menu.api";
import type { EditingMealPlan, MealPlannerFeedback } from "../types/meal-planner";
import { mealPlanAsText, suggestedTripDays } from "../utils/meal-plan-format";
import { menuErrorMessage } from "../utils/menu-errors";
import {
  useDeleteMealPlan, useExportMealPlan, useGenerateMealPlan,
  useRegenerateMealPlan, useUpdateMealPlan, useUpdateMealPlanEntry,
} from "./use-menu";

export function useMealPlanner(categories: MenuCategory[], plans: MealPlan[]) {
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
  const [editingPlan, setEditingPlan] = useState<EditingMealPlan | null>(null);
  const [feedback, setFeedback] = useState<MealPlannerFeedback>(null);

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
      .filter((category) => category.active_dish_count > 0);
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
      if (isDownloadCancelled(error)) return;
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

  return {
    selectedPlan,
    selectPlan: setSelectedPlanId,
    feedback,
    hasPlannableCategory,
    openGenerator,
    details: selectedPlan ? {
      plan: selectedPlan,
      categories,
      editingPlan,
      setEditingPlan,
      onSavePlanDetails: savePlanDetails,
      onRegenerate: () => void regenerate(selectedPlan),
      onCopy: () => void copyPlan(selectedPlan),
      onExport: () => void exportPlan(selectedPlan),
      onDelete: () => setDeletePlan(selectedPlan),
      onReplaceMeal: replaceMeal,
      isRegenerating: regeneratePlan.isPending,
      isExporting: exportMealPlan.isPending,
      isUpdatingEntry: updateEntry.isPending,
      isUpdatingPlan: updatePlan.isPending,
    } : null,
    generator: {
      isOpen: generatorOpen,
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
      isGenerating: generatePlan.isPending,
      onPlanNameChange: setPlanName,
      onTripDaysChange: setTripDays,
      onStartDateChange: setStartDate,
      onToggleCategory: toggleCategory,
      onSubmit: submitGeneration,
      onClose: () => setGeneratorOpen(false),
    },
    deletion: {
      plan: deletePlan,
      isPending: deleteMealPlan.isPending,
      confirm: confirmPlanDelete,
      close: () => setDeletePlan(null),
    },
  };
}
