import type { MealPlan, MenuCategory } from "../api/menu.api";

export function formatDate(value: string, includeWeekday: boolean): string {
  const date = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: includeWeekday ? undefined : "numeric",
    weekday: includeWeekday ? "short" : undefined,
  }).format(date);
}

export function suggestedTripDays(categories: MenuCategory[]): number {
  const activeCounts = categories
    .filter((category) => category.active_dish_count > 0)
    .map((category) => category.active_dish_count);
  if (activeCounts.length === 0) return 1;
  return Math.max(1, Math.min(5, Math.floor(Math.min(...activeCounts) / 2)));
}

export function mealPlanAsText(plan: MealPlan): string {
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
