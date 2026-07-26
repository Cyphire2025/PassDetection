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
  lunch: MealPlanEntry;
  dinner: MealPlanEntry;
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
  }: {
    categoryId: string;
    name: string;
  }): Promise<MenuCategory> => {
    const { data } = await apiClient.patch<MenuCategory>(
      API_ENDPOINTS.menu.category(categoryId),
      { name },
    );
    return data;
  },

  deleteCategory: async (categoryId: string): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.menu.category(categoryId));
  },

  createDish: async ({
    categoryId,
    name,
    notes,
  }: {
    categoryId: string;
    name: string;
    notes?: string | null;
  }): Promise<MenuDish> => {
    const { data } = await apiClient.post<MenuDish>(
      API_ENDPOINTS.menu.categoryDishes(categoryId),
      { name, notes: notes || null },
    );
    return data;
  },

  updateDish: async ({
    dishId,
    name,
    notes,
    isActive,
  }: {
    dishId: string;
    name: string;
    notes?: string | null;
    isActive: boolean;
  }): Promise<MenuDish> => {
    const { data } = await apiClient.patch<MenuDish>(
      API_ENDPOINTS.menu.dish(dishId),
      {
        name,
        notes: notes || null,
        is_active: isActive,
      },
    );
    return data;
  },

  deleteDish: async (dishId: string): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.menu.dish(dishId));
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
  }: {
    planId: string;
    categoryIds?: string[];
  }): Promise<MealPlan> => {
    const { data } = await apiClient.post<MealPlan>(
      API_ENDPOINTS.menu.regeneratePlan(planId),
      { category_ids: categoryIds },
    );
    return data;
  },

  updatePlan: async ({
    planId,
    name,
    startDate,
  }: {
    planId: string;
    name: string;
    startDate?: string | null;
  }): Promise<MealPlan> => {
    const { data } = await apiClient.patch<MealPlan>(
      API_ENDPOINTS.menu.plan(planId),
      { name, start_date: startDate || null },
    );
    return data;
  },

  updatePlanEntry: async ({
    planId,
    entryId,
    dishId,
  }: {
    planId: string;
    entryId: string;
    dishId: string;
  }): Promise<MealPlan> => {
    const { data } = await apiClient.patch<MealPlan>(
      API_ENDPOINTS.menu.planEntry(planId, entryId),
      { dish_id: dishId },
    );
    return data;
  },

  deletePlan: async (planId: string): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.menu.plan(planId));
  },
};
