import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import { createOperationsAuthorityContext, operationsActor, replacementOperationsActor } from "../test-support/operations-authority.test-fixture";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/features/tour-operations/services/offline-snapshot", () => ({ purgeAllCoordinatorOfflineSnapshots: vi.fn(async () => undefined) }));
vi.mock("@/features/tour-operations/services/browser-offline-authorization", () => ({ purgeAllBrowserOfflineAuthorizations: vi.fn(async () => undefined) }));

const contexts: ReturnType<typeof createOperationsAuthorityContext>[] = [];
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear();
  useAuthStore.setState({ user: null, hasHydrated: false, isAuthenticated: false, sessionVersion: 0 });
  useAuthStore.getState().setSession(operationsActor);
});
afterEach(() => {
  cleanup(); contexts.splice(0).forEach(context => context.cleanup());
  vi.restoreAllMocks(); localStorage.clear(); sessionStorage.clear();
});
async function initiate() {
  const context = createOperationsAuthorityContext(); contexts.push(context); context.mount();
  fireEvent.click(screen.getByRole("button", { name: "Create Manager" }));
  fireEvent.change(screen.getByLabelText(/Full name/), { target: { value: "Synthetic Manager" } });
  const email = screen.getByLabelText(/Email/);
  fireEvent.change(email, { target: { value: "manager@example.test" } });
  fireEvent.submit(email.closest("form")!);
  await waitFor(() => expect(context.entered).toHaveLength(1));
  expect(context.writes).toEqual([]);
  return context;
}

it("does not dispatch a queued manager invitation under a replacement actor after normal reset/remount", async () => {
  const context = await initiate();
  act(() => useAuthStore.getState().setSession(replacementOperationsActor));
  await waitFor(() => expect(screen.getByTestId("operations-page-owner")).toHaveTextContent(replacementOperationsActor.id));
  expect(context.unmounts).toEqual([operationsActor.id]);
  await act(async () => context.release());
  await waitFor(() => expect(context.settled).toHaveLength(1));
  expect(context.writes, JSON.stringify(context.writes)).toEqual([]);
  expect(screen.queryByRole("dialog", { name: "Manager invitation created" })).not.toBeInTheDocument();
});

it("preserves a manager invitation through same-authority profile refresh", async () => {
  const context = await initiate();
  act(() => useAuthStore.getState().setSession({ ...operationsActor, full_name: "Profile renewed" }));
  await act(async () => context.release());
  await waitFor(() => expect(context.settled).toHaveLength(1));
  expect(context.writes).toEqual([{ path: "/api/v1/admin/managers", actor: operationsActor.id,
    authority: JSON.stringify([operationsActor.id, operationsActor.role, operationsActor.agency_id]),
    body: { full_name: "Synthetic Manager", email: "manager@example.test" } }]);
  expect(context.mounts).toEqual([operationsActor.id]);
  expect(await screen.findByRole("dialog", { name: "Manager invitation created" })).toBeVisible();
});
