import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MealPlan, MenuCategory } from "../api/menu.api";
import { MealPlanner } from "./meal-planner";

const actions = vi.hoisted(() => ({
  generate: vi.fn(), regenerate: vi.fn(), update: vi.fn(), replace: vi.fn(),
  delete: vi.fn(), export: vi.fn(), copy: vi.fn(),
}));

vi.mock("../hooks/use-menu", () => ({
  useGenerateMealPlan: () => ({ mutateAsync: actions.generate, isPending: false }),
  useRegenerateMealPlan: () => ({ mutateAsync: actions.regenerate, isPending: false }),
  useUpdateMealPlan: () => ({ mutateAsync: actions.update, isPending: false }),
  useUpdateMealPlanEntry: () => ({ mutateAsync: actions.replace, isPending: false }),
  useDeleteMealPlan: () => ({ mutateAsync: actions.delete, isPending: false }),
  useExportMealPlan: () => ({ mutateAsync: actions.export, isPending: false }),
}));
vi.mock("@/lib/utils/clipboard", () => ({ copyTextToClipboard: actions.copy }));

const category: MenuCategory = {
  id: "synthetic-category", name: "Main course", sort_order: 0,
  dish_count: 4, active_dish_count: 2, created_at: "2026-10-30", updated_at: "revision-1",
  dishes: [
    ["lunch", "Lunch dish", true], ["dinner", "Dinner dish", false],
    ["replacement", "Replacement dish", true], ["paused", "Unused paused dish", false],
  ].map(([id, name, is_active], sort_order) => ({
    id: String(id), name: String(name), is_active: Boolean(is_active), sort_order,
    category_id: "synthetic-category", notes: null, created_at: "2026-10-30", updated_at: "revision-1",
  })),
};
const plan: MealPlan = {
  id: "synthetic-plan", name: "Synthetic trip", trip_days: 1, start_date: null,
  selected_category_ids: [category.id], unique_dish_count: 2,
  created_at: "2026-10-30", updated_at: "revision-1",
  days: [{
    day_number: 1, date: null,
    lunch: [{ id: "lunch-entry", day_number: 1, meal_type: "lunch", dish_id: "lunch", category_id: category.id, dish_name: "Lunch dish", category_name: category.name, notes: null }],
    dinner: [{ id: "dinner-entry", day_number: 1, meal_type: "dinner", dish_id: "dinner", category_id: category.id, dish_name: "Dinner dish", category_name: category.name, notes: null }],
  }],
};

beforeEach(() => {
  for (const action of Object.values(actions)) action.mockReset().mockResolvedValue(undefined);
});

describe("meal planner workflows", () => {
  it("generates the selected no-repeat plan with trimmed details and closes the dialog", async () => {
    actions.generate.mockResolvedValue({ ...plan, name: "Autumn trip" });
    render(<MealPlanner categories={[category]} plans={[]} onOpenLibrary={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Generate Meal Plan" }));
    const dialog = screen.getByRole("dialog", { name: "Generate meal plan" });
    await userEvent.clear(within(dialog).getByRole("textbox", { name: "Plan name" }));
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Plan name" }), "  Autumn trip  ");
    fireEvent.change(within(dialog).getByLabelText("Trip start date (optional)"), { target: { value: "2026-11-02" } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Generate plan" }));
    await waitFor(() => expect(actions.generate).toHaveBeenCalledWith({
      name: "Autumn trip", trip_days: 1, start_date: "2026-11-02", category_ids: [category.id],
    }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Autumn trip created with 2 unique dishes.");
  });

  it("blocks empty selections and dish shortages without submitting", async () => {
    render(<MealPlanner categories={[category]} plans={[]} onOpenLibrary={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Generate Meal Plan" }));
    const dialog = screen.getByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Generate plan" });
    fireEvent.change(within(dialog).getByRole("spinbutton", { name: "Number of trip days" }), { target: { value: "2" } });
    expect(submit).toBeDisabled();
    expect(dialog).toHaveTextContent("Main course: add 2");
    await userEvent.click(submit);
    await userEvent.click(within(dialog).getByRole("checkbox", { name: /Main course/ }));
    expect(submit).toBeDisabled();
    expect(dialog).toHaveTextContent("Select at least one category");
    expect(actions.generate).not.toHaveBeenCalled();
  });

  it("offers unused active replacements and preserves a currently used paused dish", async () => {
    render(<MealPlanner categories={[category]} plans={[plan]} onOpenLibrary={vi.fn()} />);
    const lunch = screen.getByRole("combobox", { name: "Change day 1 lunch Main course" });
    const dinner = screen.getByRole("combobox", { name: "Change day 1 dinner Main course" });
    expect(within(lunch).getAllByRole("option").map(option => option.textContent)).toEqual(["Lunch dish", "Replacement dish"]);
    expect(within(dinner).getAllByRole("option").map(option => option.textContent)).toEqual(["Dinner dish (paused)", "Replacement dish"]);
    await userEvent.selectOptions(lunch, "replacement");
    await waitFor(() => expect(actions.replace).toHaveBeenCalledWith({ planId: plan.id, entryId: "lunch-entry", dishId: "replacement" }));
    expect(screen.getByRole("status")).toHaveTextContent("Day 1 lunch updated.");
  });

  it("saves details, treats cancelled exports quietly and keeps failed deletion reviewable", async () => {
    render(<MealPlanner categories={[category]} plans={[plan]} onOpenLibrary={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    await userEvent.clear(screen.getByLabelText("Plan name"));
    await userEvent.type(screen.getByLabelText("Plan name"), "  Updated trip  ");
    await userEvent.click(screen.getByRole("button", { name: "Save details" }));
    await waitFor(() => expect(actions.update).toHaveBeenCalledWith({ planId: plan.id, name: "Updated trip", startDate: null }));
    expect(screen.getByRole("status")).toHaveTextContent("Plan details updated.");

    actions.export.mockRejectedValueOnce(new DOMException("Synthetic cancellation", "AbortError"));
    await userEvent.click(screen.getByRole("button", { name: "Excel" }));
    await waitFor(() => expect(actions.export).toHaveBeenCalledWith({ planId: plan.id, planName: plan.name }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    actions.delete.mockRejectedValueOnce(new Error("Plan changed. Refresh and retry."));
    await userEvent.click(screen.getByRole("button", { name: `Delete ${plan.name}` }));
    const dialog = screen.getByRole("dialog", { name: "Delete meal plan?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete plan" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Plan changed. Refresh and retry."));
    expect(dialog).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete plan" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(actions.delete).toHaveBeenCalledTimes(2);
  });

  it("falls back to the current roster when a selected saved plan disappears", async () => {
    const second = { ...plan, id: "second-plan", name: "Next trip" };
    const { rerender } = render(<MealPlanner categories={[category]} plans={[plan, second]} onOpenLibrary={vi.fn()} />);
    rerender(<MealPlanner categories={[category]} plans={[second]} onOpenLibrary={vi.fn()} />);
    expect(screen.getByRole("heading", { name: second.name })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Regenerate" }));
    await waitFor(() => expect(actions.regenerate).toHaveBeenCalledWith({ planId: second.id, categoryIds: [category.id] }));
  });
});
