import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { QUERY_KEYS } from "@/constants";
import {
  menuApi,
  type GenerateMealPlanInput,
  type MenuCategory,
  type MenuDish,
  type MenuWorkspace,
} from "../api/menu.api";

export function useMenuWorkspace() {
  return useQuery({
    queryKey: QUERY_KEYS.menu.workspace,
    queryFn: menuApi.workspace,
  });
}

function useRefreshMenu() {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({ queryKey: QUERY_KEYS.menu.workspace });
}

export function useCreateMenuCategory() {
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: menuApi.createCategory,
    onSuccess: refresh,
  });
}

export function useUpdateMenuCategory() {
  const queryClient = useQueryClient();
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: ({ categoryId, name }: { categoryId: string; name: string }) => {
      const category = requireCategory(currentWorkspace(queryClient), categoryId);
      return menuApi.updateCategory({
        categoryId,
        name,
        expectedUpdatedAt: category.updated_at,
      });
    },
    onSettled: refresh,
  });
}

export function useDeleteMenuCategory() {
  const queryClient = useQueryClient();
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: (categoryId: string) => {
      const category = requireCategory(currentWorkspace(queryClient), categoryId);
      return menuApi.deleteCategory({
        categoryId,
        expectedUpdatedAt: category.updated_at,
      });
    },
    onSettled: refresh,
  });
}

export function useCreateMenuDish() {
  const queryClient = useQueryClient();
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: ({
      categoryId,
      name,
      notes,
    }: {
      categoryId: string;
      name: string;
      notes?: string | null;
    }) => {
      const category = requireCategory(currentWorkspace(queryClient), categoryId);
      return menuApi.createDish({
        categoryId,
        name,
        notes,
        expectedCategoryUpdatedAt: category.updated_at,
      });
    },
    onSettled: refresh,
  });
}

export function useUpdateMenuDish() {
  const queryClient = useQueryClient();
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: ({
      dishId,
      name,
      notes,
      isActive,
    }: {
      dishId: string;
      name: string;
      notes?: string | null;
      isActive: boolean;
    }) => {
      const { category, dish } = requireDish(currentWorkspace(queryClient), dishId);
      return menuApi.updateDish({
        dishId,
        name,
        notes,
        isActive,
        expectedUpdatedAt: dish.updated_at,
        expectedCategoryUpdatedAt: category.updated_at,
      });
    },
    onSettled: refresh,
  });
}

export function useDeleteMenuDish() {
  const queryClient = useQueryClient();
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: (dishId: string) => {
      const { category, dish } = requireDish(currentWorkspace(queryClient), dishId);
      return menuApi.deleteDish({
        dishId,
        expectedUpdatedAt: dish.updated_at,
        expectedCategoryUpdatedAt: category.updated_at,
      });
    },
    onSettled: refresh,
  });
}

export function useGenerateMealPlan() {
  const queryClient = useQueryClient();
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: (input: GenerateMealPlanInput) => {
      const workspace = currentWorkspace(queryClient);
      const categoryIds = input.category_ids
        ?? workspace.categories
          .filter((category) => category.active_dish_count > 0)
          .map((category) => category.id);
      return menuApi.generatePlan({
        ...input,
        category_ids: categoryIds,
        expected_category_revisions: categoryRevisions(workspace, categoryIds),
      });
    },
    onSettled: refresh,
  });
}

export function useRegenerateMealPlan() {
  const queryClient = useQueryClient();
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: ({ planId, categoryIds }: { planId: string; categoryIds?: string[] }) => {
      const workspace = currentWorkspace(queryClient);
      const plan = requirePlan(workspace, planId);
      const selectedIds = categoryIds ?? plan.selected_category_ids;
      return menuApi.regeneratePlan({
        planId,
        categoryIds: selectedIds,
        expectedUpdatedAt: plan.updated_at,
        expectedCategoryRevisions: categoryRevisions(workspace, selectedIds),
      });
    },
    onSettled: refresh,
  });
}

export function useUpdateMealPlan() {
  const queryClient = useQueryClient();
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: ({
      planId,
      name,
      startDate,
    }: {
      planId: string;
      name: string;
      startDate?: string | null;
    }) => {
      const plan = requirePlan(currentWorkspace(queryClient), planId);
      return menuApi.updatePlan({
        planId,
        name,
        startDate,
        expectedUpdatedAt: plan.updated_at,
      });
    },
    onSettled: refresh,
  });
}

export function useUpdateMealPlanEntry() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      planId,
      entryId,
      dishId,
    }: {
      planId: string;
      entryId: string;
      dishId: string;
    }) => {
      const workspace = currentWorkspace(queryClient);
      const plan = requirePlan(workspace, planId);
      const { category, dish } = requireDish(workspace, dishId);
      return menuApi.updatePlanEntry({
        planId,
        entryId,
        dishId,
        expectedUpdatedAt: plan.updated_at,
        expectedDishUpdatedAt: dish.updated_at,
        expectedCategoryUpdatedAt: category.updated_at,
      });
    },
    onSuccess: (updatedPlan) => {
      queryClient.setQueryData(
        QUERY_KEYS.menu.workspace,
        (
          workspace:
            | Awaited<ReturnType<typeof menuApi.workspace>>
            | undefined,
        ) => {
          if (!workspace) return workspace;
          return {
            ...workspace,
            plans: workspace.plans.map((plan) =>
              plan.id === updatedPlan.id ? updatedPlan : plan,
            ),
          };
        },
      );
    },
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.menu.workspace }),
  });
}

export function useDeleteMealPlan() {
  const queryClient = useQueryClient();
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: (planId: string) => {
      const plan = requirePlan(currentWorkspace(queryClient), planId);
      return menuApi.deletePlan({
        planId,
        expectedUpdatedAt: plan.updated_at,
      });
    },
    onSettled: refresh,
  });
}

export function useExportMealPlan() {
  return useMutation({
    mutationFn: menuApi.exportPlan,
  });
}

function currentWorkspace(queryClient: ReturnType<typeof useQueryClient>): MenuWorkspace {
  const workspace = queryClient.getQueryData<MenuWorkspace>(QUERY_KEYS.menu.workspace);
  if (!workspace) {
    throw new Error("The menu workspace is not loaded. Refresh and retry the change.");
  }
  return workspace;
}

function requireCategory(workspace: MenuWorkspace, categoryId: string): MenuCategory {
  const category = workspace.categories.find((item) => item.id === categoryId);
  if (!category) {
    throw new Error("The menu category is no longer available. Refresh and retry.");
  }
  return category;
}

function requireDish(
  workspace: MenuWorkspace,
  dishId: string,
): { category: MenuCategory; dish: MenuDish } {
  for (const category of workspace.categories) {
    const dish = category.dishes.find((item) => item.id === dishId);
    if (dish) return { category, dish };
  }
  throw new Error("The menu dish is no longer available. Refresh and retry.");
}

function requirePlan(workspace: MenuWorkspace, planId: string) {
  const plan = workspace.plans.find((item) => item.id === planId);
  if (!plan) {
    throw new Error("The meal plan is no longer available. Refresh and retry.");
  }
  return plan;
}

function categoryRevisions(
  workspace: MenuWorkspace,
  categoryIds: readonly string[],
): Record<string, string> {
  return Object.fromEntries(
    categoryIds.map((categoryId) => {
      const category = requireCategory(workspace, categoryId);
      return [category.id, category.updated_at];
    }),
  );
}
