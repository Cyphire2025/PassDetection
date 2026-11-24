export type EditingMealPlan = { id: string; name: string; startDate: string };

export type MealPlannerFeedback = {
  kind: "success" | "error";
  message: string;
} | null;
