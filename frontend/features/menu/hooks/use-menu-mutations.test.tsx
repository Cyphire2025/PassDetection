import type { ReactNode } from "react";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { MutationCache, QueryClient, QueryClientProvider, type UseMutationResult } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi, type Mock } from "vitest";
import { QUERY_KEYS } from "@/constants";
import { useAuthStore } from "@/stores/auth.store";
import { AuthenticatedContent } from "@/features/auth/components/authenticated-content";
import { SessionLifecycle } from "@/providers/session-lifecycle";
import { menuApi, type MealPlan, type MenuCategory, type MenuWorkspace } from "../api/menu.api";
import { menuActor, nextMenuActor } from "../test-support/menu-authority.test-fixture";
import { useCreateMenuCategory, useUpdateMenuCategory, useDeleteMenuCategory, useCreateMenuDish, useUpdateMenuDish, useDeleteMenuDish, useGenerateMealPlan, useRegenerateMealPlan, useUpdateMealPlan, useUpdateMealPlanEntry, useDeleteMealPlan, useExportMealPlan, } from "./use-menu";
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/features/tour-operations/services/offline-snapshot", () => ({ purgeAllCoordinatorOfflineSnapshots: vi.fn(async () => undefined) }));
vi.mock("@/features/tour-operations/services/browser-offline-authorization", () => ({ purgeAllBrowserOfflineAuthorizations: vi.fn(async () => undefined) }));
vi.mock("../api/menu.api", async (original) => {
  const actual = await original<typeof import("../api/menu.api")>();
  return { ...actual, menuApi: Object.fromEntries(Object.keys(actual.menuApi).map(name => [name, vi.fn()])) };
});
const category: MenuCategory = { id: "category", name: "Synthetic category", sort_order: 0, dish_count: 2, active_dish_count: 2,
  created_at: "2026-10-31", updated_at: "category-revision", dishes: [0, 1].map(index => ({ id: `dish-${index}`, category_id: "category",
    name: `Synthetic dish ${index}`, notes: null, is_active: true, sort_order: index, created_at: "2026-10-31", updated_at: `dish-revision-${index}` })) };
const plan: MealPlan = { id: "plan", name: "Synthetic plan", trip_days: 1, start_date: null, selected_category_ids: [category.id], unique_dish_count: 2,
  days: [], created_at: "2026-10-31", updated_at: "plan-revision" };
const workspace: MenuWorkspace = { categories: [category], plans: [plan], total_dishes: 2, active_dishes: 2, max_trip_days_without_repeats: 1 };
interface CallbackReceipt {
  phase: "success" | "settled";
  variables: unknown;
  context: unknown;
}

function operation<TData, TError, TVariables, TContext>(
  name: keyof typeof menuApi,
  useAction: () => UseMutationResult<TData, TError, TVariables, TContext>,
  input: TVariables,
  expectedArgs: unknown[],
) {
  return {
    name,
    input,
    expectedArgs,
    useBoundAction(callbacks: CallbackReceipt[]) {
      const action = useAction();
      return {
        ...action,
        execute: () => action.mutateAsync(input, {
          onSuccess: (_data, variables, context) => { callbacks.push({ phase: "success", variables, context }); },
          onSettled: (_data, _error, variables, context) => { callbacks.push({ phase: "settled", variables, context }); },
        }),
      };
    },
  };
}
const cases = [
  operation("createCategory", useCreateMenuCategory, "Synthetic", ["Synthetic"]),
  operation("updateCategory", useUpdateMenuCategory, { categoryId: "category", name: "Updated" }, [{ categoryId: "category", name: "Updated", expectedUpdatedAt: "category-revision" }]),
  operation("deleteCategory", useDeleteMenuCategory, "category", [{ categoryId: "category", expectedUpdatedAt: "category-revision" }]),
  operation("createDish", useCreateMenuDish, { categoryId: "category", name: "New dish", notes: null }, [{ categoryId: "category", name: "New dish", notes: null, expectedCategoryUpdatedAt: "category-revision" }]),
  operation("updateDish", useUpdateMenuDish, { dishId: "dish-0", name: "Updated dish", notes: null, isActive: false }, [{ dishId: "dish-0", name: "Updated dish", notes: null, isActive: false, expectedUpdatedAt: "dish-revision-0", expectedCategoryUpdatedAt: "category-revision" }]),
  operation("deleteDish", useDeleteMenuDish, "dish-0", [{ dishId: "dish-0", expectedUpdatedAt: "dish-revision-0", expectedCategoryUpdatedAt: "category-revision" }]),
  operation("generatePlan", useGenerateMealPlan, { name: "Synthetic plan", trip_days: 1 }, [{ name: "Synthetic plan", trip_days: 1, category_ids: ["category"], expected_category_revisions: { category: "category-revision" } }]),
  operation("regeneratePlan", useRegenerateMealPlan, { planId: "plan" }, [{ planId: "plan", categoryIds: ["category"], expectedUpdatedAt: "plan-revision", expectedCategoryRevisions: { category: "category-revision" } }]),
  operation("updatePlan", useUpdateMealPlan, { planId: "plan", name: "Updated plan", startDate: null }, [{ planId: "plan", name: "Updated plan", startDate: null, expectedUpdatedAt: "plan-revision" }]),
  operation("updatePlanEntry", useUpdateMealPlanEntry, { planId: "plan", entryId: "entry", dishId: "dish-0" }, [{ planId: "plan", entryId: "entry", dishId: "dish-0", expectedUpdatedAt: "plan-revision", expectedDishUpdatedAt: "dish-revision-0", expectedCategoryUpdatedAt: "category-revision" }]),
  operation("deletePlan", useDeleteMealPlan, "plan", [{ planId: "plan", expectedUpdatedAt: "plan-revision" }]),
  operation("exportPlan", useExportMealPlan, { planId: "plan", planName: "Synthetic plan" }, [{ planId: "plan", planName: "Synthetic plan" }]),
];
const clients: QueryClient[] = [];
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  useAuthStore.setState({ user: null, hasHydrated: false, isAuthenticated: false, sessionVersion: 0 });
  useAuthStore.getState().setSession(menuActor);
  for (const method of Object.values(menuApi))
    (method as unknown as Mock<(...args: unknown[]) => Promise<unknown>>).mockReset().mockResolvedValue(plan);
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach(client => client.clear());
});
function setup(row: typeof cases[number]) {
  const gate = Promise.withResolvers<void>();
  let entered = 0;
  const callbacks: CallbackReceipt[] = [];
  const client = new QueryClient({
    mutationCache: new MutationCache({
      onMutate: async () => {
        entered++;
        await gate.promise;
      },
    }),
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  client.setQueryData(QUERY_KEYS.menu.workspace, workspace);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <SessionLifecycle queryClient={client} />
      <AuthenticatedContent>{children}</AuthenticatedContent>
    </QueryClientProvider>
  );
  const hook = renderHook(() => row.useBoundAction(callbacks), { wrapper });
  return { ...hook, client, callbacks, release: () => gate.resolve(), entered: () => entered };
}
it.each(cases)("blocks queued $name and callbacks after actual actor reset with a replacement loaded workspace", async (row) => {
  const context = setup(row);
  let pending!: Promise<unknown>;
  act(() => { pending = context.result.current.execute(); });
  const rejected = expect(pending).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
  await waitFor(() => expect(context.entered()).toBe(1));
  act(() => useAuthStore.getState().setSession(nextMenuActor));
  // Both actors may legitimately see the same agency resources. Cache absence is not the owner fence.
  context.client.setQueryData(QUERY_KEYS.menu.workspace, workspace);
  await act(async () => {
    context.release();
    await rejected;
  });
  expect(menuApi[row.name]).not.toHaveBeenCalled();
  expect(context.callbacks).toEqual([]);
});
it.each(cases)("preserves $name revisions variables callbacks and reset through same-owner renewal", async (row) => {
  const context = setup(row);
  let pending!: Promise<unknown>;
  act(() => { pending = context.result.current.execute(); });
  await waitFor(() => expect(context.entered()).toBe(1));
  act(() => useAuthStore.getState().setSession({ ...menuActor, full_name: "Profile renewed" }));
  await act(async () => {
    context.release();
    await pending;
  });
  const method = vi.mocked(menuApi[row.name]);
  expect(method).toHaveBeenCalledOnce();
  expect(method.mock.calls[0].slice(0, row.expectedArgs.length)).toEqual(row.expectedArgs);
  expect(context.result.current.variables).toEqual(row.input);
  expect(context.callbacks).toEqual([{ phase: "success", variables: row.input, context: undefined }, { phase: "settled", variables: row.input, context: undefined }]);
  act(() => context.result.current.reset());
  await waitFor(() => expect(context.result.current.isIdle).toBe(true));
  expect(context.result.current.variables).toBeUndefined();
});
