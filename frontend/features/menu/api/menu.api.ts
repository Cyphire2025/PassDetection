import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export interface MenuDish {
  id: string;
  category_id: string;
  name: string;
  notes: string | null;
  is_active: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface MenuCategory {
  id: string;
  name: string;
  sort_order: number;
  dish_count: number;
  active_dish_count: number;
  dishes: MenuDish[];
  created_at: string;
  updated_at: string;
}

export interface MealPlanEntry {
  id: string;
  day_number: number;
  meal_type: "lunch" | "dinner";
  dish_id: string | null;
  category_id: string | null;
  dish_name: string;
  category_name: string;
  notes: string | null;
}

export interface MealPlanDay {
  day_number: number;
  date: string | null;
  lunch: MealPlanEntry[];
  dinner: MealPlanEntry[];
}

export interface MealPlan {
  id: string;
  name: string;
  trip_days: number;
  start_date: string | null;
  selected_category_ids: string[];
  unique_dish_count: number;
  days: MealPlanDay[];
  created_at: string;
  updated_at: string;
}

export interface MenuWorkspace {
  categories: MenuCategory[];
  plans: MealPlan[];
  total_dishes: number;
  active_dishes: number;
  max_trip_days_without_repeats: number;
}

export interface GenerateMealPlanInput {
  name: string;
  trip_days: number;
  start_date?: string | null;
  category_ids?: string[];
  expected_category_revisions?: Record<string, string>;
}

export const menuApi = {
  workspace: async (): Promise<MenuWorkspace> => {
    const { data } = await apiClient.get<MenuWorkspace>(
      API_ENDPOINTS.menu.workspace,
    );
    return data;
  },

  createCategory: async (name: string): Promise<MenuCategory> => {
    const { data } = await apiClient.post<MenuCategory>(
      API_ENDPOINTS.menu.categories,
      { name },
    );
    return data;
  },

  updateCategory: async ({
    categoryId,
    name,
    expectedUpdatedAt,
  }: {
    categoryId: string;
    name: string;
    expectedUpdatedAt: string;
  }): Promise<MenuCategory> => {
    const { data } = await apiClient.patch<MenuCategory>(
      API_ENDPOINTS.menu.category(categoryId),
      { name, expected_updated_at: expectedUpdatedAt },
    );
    return data;
  },

  deleteCategory: async ({
    categoryId,
    expectedUpdatedAt,
  }: {
    categoryId: string;
    expectedUpdatedAt: string;
  }): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.menu.category(categoryId), {
      data: { expected_updated_at: expectedUpdatedAt },
    });
  },

  createDish: async ({
    categoryId,
    name,
    notes,
    expectedCategoryUpdatedAt,
  }: {
    categoryId: string;
    name: string;
    notes?: string | null;
    expectedCategoryUpdatedAt: string;
  }): Promise<MenuDish> => {
    const { data } = await apiClient.post<MenuDish>(
      API_ENDPOINTS.menu.categoryDishes(categoryId),
      {
        name,
        notes: notes || null,
        expected_category_updated_at: expectedCategoryUpdatedAt,
      },
    );
    return data;
  },

  updateDish: async ({
    dishId,
    name,
    notes,
    isActive,
    expectedUpdatedAt,
    expectedCategoryUpdatedAt,
  }: {
    dishId: string;
    name: string;
    notes?: string | null;
    isActive: boolean;
    expectedUpdatedAt: string;
    expectedCategoryUpdatedAt: string;
  }): Promise<MenuDish> => {
    const { data } = await apiClient.patch<MenuDish>(
      API_ENDPOINTS.menu.dish(dishId),
      {
        name,
        notes: notes || null,
        is_active: isActive,
        expected_updated_at: expectedUpdatedAt,
        expected_category_updated_at: expectedCategoryUpdatedAt,
      },
    );
    return data;
  },

  deleteDish: async ({
    dishId,
    expectedUpdatedAt,
    expectedCategoryUpdatedAt,
  }: {
    dishId: string;
    expectedUpdatedAt: string;
    expectedCategoryUpdatedAt: string;
  }): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.menu.dish(dishId), {
      data: {
        expected_updated_at: expectedUpdatedAt,
        expected_category_updated_at: expectedCategoryUpdatedAt,
      },
    });
  },

  generatePlan: async (
    input: GenerateMealPlanInput,
  ): Promise<MealPlan> => {
    const { data } = await apiClient.post<MealPlan>(
      API_ENDPOINTS.menu.generatePlan,
      input,
    );
    return data;
  },

  regeneratePlan: async ({
    planId,
    categoryIds,
    expectedUpdatedAt,
    expectedCategoryRevisions,
  }: {
    planId: string;
    categoryIds?: string[];
    expectedUpdatedAt: string;
    expectedCategoryRevisions: Record<string, string>;
  }): Promise<MealPlan> => {
    const { data } = await apiClient.post<MealPlan>(
      API_ENDPOINTS.menu.regeneratePlan(planId),
      {
        category_ids: categoryIds,
        expected_updated_at: expectedUpdatedAt,
        expected_category_revisions: expectedCategoryRevisions,
      },
    );
    return data;
  },

  updatePlan: async ({
    planId,
    name,
    startDate,
    expectedUpdatedAt,
  }: {
    planId: string;
    name: string;
    startDate?: string | null;
    expectedUpdatedAt: string;
  }): Promise<MealPlan> => {
    const { data } = await apiClient.patch<MealPlan>(
      API_ENDPOINTS.menu.plan(planId),
      {
        name,
        start_date: startDate || null,
        expected_updated_at: expectedUpdatedAt,
      },
    );
    return data;
  },

  updatePlanEntry: async ({
    planId,
    entryId,
    dishId,
    expectedUpdatedAt,
    expectedDishUpdatedAt,
    expectedCategoryUpdatedAt,
  }: {
    planId: string;
    entryId: string;
    dishId: string;
    expectedUpdatedAt: string;
    expectedDishUpdatedAt: string;
    expectedCategoryUpdatedAt: string;
  }): Promise<MealPlan> => {
    const { data } = await apiClient.patch<MealPlan>(
      API_ENDPOINTS.menu.planEntry(planId, entryId),
      {
        dish_id: dishId,
        expected_updated_at: expectedUpdatedAt,
        expected_dish_updated_at: expectedDishUpdatedAt,
        expected_category_updated_at: expectedCategoryUpdatedAt,
      },
    );
    return data;
  },

  deletePlan: async ({
    planId,
    expectedUpdatedAt,
  }: {
    planId: string;
    expectedUpdatedAt: string;
  }): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.menu.plan(planId), {
      data: { expected_updated_at: expectedUpdatedAt },
    });
  },

  exportPlan: async ({
    planId,
    planName,
  }: {
    planId: string;
    planName: string;
  }): Promise<void> => {
    const response = await apiClient.get<Blob>(
      API_ENDPOINTS.menu.planExport(planId),
      { responseType: "blob" },
    );
    downloadBlob(response.data, `${safeFilename(planName)}.xlsx`);
  },
};

function safeFilename(value: string): string {
  return (
    value
      .trim()
      .replace(/[^a-z0-9]+/gi, "-")
      .replace(/^-+|-+$/g, "")
      .toLowerCase()
      .slice(0, 80) || "meal-plan"
  );
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
