import type { ComponentType } from "react";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import { createMenuAuthorityContext, menuActor, nextMenuActor } from "../test-support/menu-authority.test-fixture";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("next/dynamic", async () => {
  const { lazy } = await import("react");
  return { default: (loader: () => Promise<ComponentType>) => lazy(async () => ({ default: await loader() })) };
});
vi.mock("@/features/tour-operations/services/offline-snapshot", () => ({ purgeAllCoordinatorOfflineSnapshots: vi.fn(async () => undefined) }));
vi.mock("@/features/tour-operations/services/browser-offline-authorization", () => ({ purgeAllBrowserOfflineAuthorizations: vi.fn(async () => undefined) }));

const contexts: ReturnType<typeof createMenuAuthorityContext>[] = [];
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear();
  useAuthStore.setState({ user: null, hasHydrated: false, isAuthenticated: false, sessionVersion: 0 });
  useAuthStore.getState().setSession(menuActor);
});
afterEach(() => {
  cleanup(); contexts.splice(0).forEach(context => context.cleanup());
  vi.restoreAllMocks(); localStorage.clear(); sessionStorage.clear();
});
async function initiate() {
  const context = createMenuAuthorityContext(); contexts.push(context); context.mount();
  const name = await screen.findByRole("textbox", { name: "New category name" });
  fireEvent.change(name, { target: { value: "  Synthetic A category  " } });
  fireEvent.submit(name.closest("form")!);
  await waitFor(() => expect(context.entered).toHaveLength(1));
  expect(context.writes).toEqual([]);
  return context;
}
it("does not dispatch the original menu form under a replacement actor after normal reset/remount", async () => {
  const context = await initiate();
  act(() => useAuthStore.getState().setSession(nextMenuActor));
  await waitFor(() => expect(screen.getByTestId("menu-page-owner")).toHaveTextContent(nextMenuActor.id));
  expect(context.unmounts).toEqual([menuActor.id]);
  await act(async () => context.release());
  await waitFor(() => expect(context.settled).toHaveLength(1));
  expect(context.writes, JSON.stringify(context.writes)).toEqual([]);
});
it("preserves the original menu category form through same-authority profile renewal", async () => {
  const context = await initiate();
  act(() => useAuthStore.getState().setSession({ ...menuActor, full_name: "Profile renewed" }));
  await act(async () => context.release());
  await waitFor(() => expect(context.settled).toHaveLength(1));
  expect(context.writes).toEqual([{ actor: menuActor.id,
    authority: JSON.stringify([menuActor.id, menuActor.role, menuActor.agency_id]), body: { name: "Synthetic A category" } }]);
  expect(await screen.findByText("Category added.")).toHaveAttribute("role", "status");
  expect(context.mounts).toEqual([menuActor.id]);
});
