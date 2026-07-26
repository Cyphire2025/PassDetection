import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { QUERY_KEYS } from "@/constants";
import { menuApi } from "../api/menu.api";

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
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: menuApi.updateCategory,
    onSuccess: refresh,
  });
}

export function useDeleteMenuCategory() {
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: menuApi.deleteCategory,
    onSuccess: refresh,
  });
}

export function useCreateMenuDish() {
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: menuApi.createDish,
    onSuccess: refresh,
  });
}

export function useUpdateMenuDish() {
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: menuApi.updateDish,
    onSuccess: refresh,
  });
}

export function useDeleteMenuDish() {
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: menuApi.deleteDish,
    onSuccess: refresh,
  });
}

export function useGenerateMealPlan() {
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: menuApi.generatePlan,
    onSuccess: refresh,
  });
}

export function useRegenerateMealPlan() {
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: menuApi.regeneratePlan,
    onSuccess: refresh,
  });
}

export function useUpdateMealPlan() {
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: menuApi.updatePlan,
    onSuccess: refresh,
  });
}

export function useUpdateMealPlanEntry() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: menuApi.updatePlanEntry,
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
  });
}

export function useDeleteMealPlan() {
  const refresh = useRefreshMenu();
  return useMutation({
    mutationFn: menuApi.deletePlan,
    onSuccess: refresh,
  });
}
