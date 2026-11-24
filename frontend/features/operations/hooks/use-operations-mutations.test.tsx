import type { ReactNode } from "react";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { MutationCache, QueryClient, QueryClientProvider, type UseMutationResult } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi, type Mock } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import { AuthenticatedContent } from "@/features/auth/components/authenticated-content";
import { SessionLifecycle } from "@/providers/session-lifecycle";
import { operationsApi, type RoomingWorkspace } from "../api/operations.api";
import { operationsActor, replacementOperationsActor } from "../test-support/operations-authority.test-fixture";
import {
  useCreateManager, useDeleteManager, useCreateStaff, useAssignStaffGroups,
  useManagedAccountActions, useAuditLogExport, useCreateTourCoordinator, useRoomingActions,
  useAssignTourGroupCoordinators, useAssignTourGroupPassengers,
  useCompleteManagedAttendanceSession, useCreateManagedAttendanceSession, useSendQrBroadcast, usePassengerQrLifecycle,
} from "./use-operations";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/features/tour-operations/services/offline-snapshot", () => ({ purgeAllCoordinatorOfflineSnapshots: vi.fn(async () => undefined) }));
vi.mock("@/features/tour-operations/services/browser-offline-authorization", () => ({ purgeAllBrowserOfflineAuthorizations: vi.fn(async () => undefined) }));
vi.mock("../api/operations.api", async original => {
  const actual = await original<typeof import("../api/operations.api")>();
  return { ...actual, operationsApi: Object.fromEntries(Object.keys(actual.operationsApi).map(name => [name, vi.fn()])) };
});
function operation<TData, TError, TVariables, TContext>(name: keyof typeof operationsApi,
  useAction: () => UseMutationResult<TData, TError, TVariables, TContext>, input: TVariables, expectedArgs: unknown[]) {
  return { name, input, expectedArgs,
    useBoundAction(callbacks: Array<{ phase: string; variables: unknown; context: unknown }>) {
      const action = useAction();
      return { ...action, execute: () => action.mutateAsync(input, {
        onSuccess: (_data, variables, context) => { callbacks.push({ phase: "success", variables, context }); },
        onSettled: (_data, _error, variables, context) => { callbacks.push({ phase: "settled", variables, context }); },
      }) };
    },
  };
}
const body = { full_name: "Synthetic account", email: "synthetic@example.test" };
const audit = { filters: { start_at: "2026-10-01", end_at: "2026-10-02" }, signal: new AbortController().signal };
const hotelBody = { hotel_name: "Synthetic hotel" };
const roomingKey = ["operations", "rooming", "group"];
const workspace: RoomingWorkspace = {
  group_id: "group", group_name: "Synthetic trip", destination: null, total_passengers: 0, passengers: [], hotels: [{
    id: "hotel", hotel_name: "Synthetic hotel", city: null, check_in_date: null, check_out_date: null,
    rooms: [], unallocated_passengers: [], selected_passengers: [], selected_passenger_count: 0,
    allocation_priority_fields: [], allocation_revision: 1, allocation_is_current: false,
    allocated_passenger_count: 0, capacity_total: 0,
  }],
};
const cases = [
  operation("createManager", useCreateManager, body, [body]),
  operation("deleteManager", useDeleteManager, { managerId: "account", deleteOwnedData: false }, ["account", false]),
  operation("createStaff", useCreateStaff, body, [body]),
  operation("assignStaffGroups", useAssignStaffGroups, { staffId: "account", groupIds: ["group"] }, ["account", ["group"]]),
  operation("resetManagedAccountPassword", () => useManagedAccountActions().resetPassword, "account", ["account"]),
  operation("resetManagedAccountMfa", () => useManagedAccountActions().resetMfa, "account", ["account"]),
  operation("revokeManagedAccountSessions", () => useManagedAccountActions().revokeSessions, "account", ["account"]),
  operation("setManagedAccountStatus", () => useManagedAccountActions().setStatus, { accountId: "account", isActive: false }, ["account", false]),
  operation("deleteManagedAccount", () => useManagedAccountActions().deleteAccount, "account", ["account"]),
  operation("exportAuditLogs", useAuditLogExport, audit, [audit]),
  operation("createTourCoordinator", useCreateTourCoordinator, { ...body, password: "synthetic-only-password" }, [{ ...body, password: "synthetic-only-password" }]),
  operation("createRoomingHotel", () => useRoomingActions("group").createHotel, hotelBody, ["group", hotelBody]),
  operation("updateRoomingHotel", () => useRoomingActions("group").updateHotel, { hotelId: "hotel", ...hotelBody }, ["hotel", hotelBody]),
  operation("updateRoomingPassengerSelection", () => useRoomingActions("group").selectHotelPassengers,
    { hotelId: "hotel", passengerIds: [] }, ["hotel", { passenger_ids: [], mode: "add", expected_allocation_revisions: { hotel: 1 } }]),
  operation("updateRoomingVip", () => useRoomingActions("group").setPassengerVip,
    { hotelId: "hotel", passengerIds: [], isVip: true }, ["hotel", { passenger_ids: [], is_vip: true, expected_allocation_revisions: { hotel: 1 } }]),
  operation("autoAllocateRoomingHotel", () => useRoomingActions("group").autoAllocate,
    { hotelId: "hotel", priorityFields: [] }, ["hotel", { priority_fields: [], expected_allocation_revisions: { hotel: 1 } }]),
  operation("assignTourGroupCoordinators", useAssignTourGroupCoordinators, { groupId: "group", coordinatorIds: [] }, ["group", []]),
  operation("assignTourGroupPassengers", useAssignTourGroupPassengers,
    { groupId: "group", passengerIds: [], coordinatorId: null }, ["group", [], null]),
  operation("completeManagedAttendanceSession", useCompleteManagedAttendanceSession,
    { groupId: "group", sessionId: "activity" }, [{ groupId: "group", sessionId: "activity" }]),
  operation("createManagedAttendanceSession", useCreateManagedAttendanceSession,
    { groupId: "group", name: "Synthetic activity" }, [{ groupId: "group", name: "Synthetic activity" }]),
  operation("sendQrBroadcast", () => useSendQrBroadcast("group"),
    { qr_token_ids: [], message_content: "Synthetic message" }, ["group", { qr_token_ids: [], message_content: "Synthetic message" }]),
  operation("generatePassengerQr", () => usePassengerQrLifecycle("group").generate, "passenger", ["group", "passenger"]),
  operation("regeneratePassengerQr", () => usePassengerQrLifecycle("group").regenerate, "passenger", ["group", "passenger"]),
  operation("revokePassengerQr", () => usePassengerQrLifecycle("group").revoke, "passenger", ["group", "passenger"]),
  operation("setPassengerQrActive", () => usePassengerQrLifecycle("group").setActive,
    { passengerId: "passenger", isActive: false }, ["group", "passenger", false]),
  operation("setPassengerQrExpiration", () => usePassengerQrLifecycle("group").expire, "passenger", ["group", "passenger", expect.stringMatching(/^\d{4}-\d\d-\d\dT/)]),
];
const clients: QueryClient[] = [];
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear();
  useAuthStore.setState({ user: null, hasHydrated: false, isAuthenticated: false, sessionVersion: 0 });
  useAuthStore.getState().setSession(operationsActor);
  for (const method of Object.values(operationsApi)) {
    (method as unknown as Mock<(...args: unknown[]) => Promise<unknown>>).mockReset().mockResolvedValue({
      id: "created", group_id: "group", changed: false, current_revisions: {}, hotels: [], passengers: [], truncated: false,
    });
  }
});
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); });
function setup(row: typeof cases[number]) {
  const gate = Promise.withResolvers<void>();
  let entered = 0;
  const callbacks: Array<{ phase: string; variables: unknown; context: unknown }> = [];
  const client = new QueryClient({ mutationCache: new MutationCache({ onMutate: async () => { entered++; await gate.promise; } }),
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client); client.setQueryData(roomingKey, workspace);
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>
    <SessionLifecycle queryClient={client} /><AuthenticatedContent>{children}</AuthenticatedContent>
  </QueryClientProvider>;
  const hook = renderHook(() => row.useBoundAction(callbacks), { wrapper });
  return { ...hook, client, callbacks, release: () => gate.resolve(), entered: () => entered };
}

it.each(cases)("blocks queued $name dispatch and callbacks after a real actor reset", async row => {
  const context = setup(row);
  let pending!: Promise<unknown>;
  act(() => { pending = context.result.current.execute(); });
  const rejected = expect(pending).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
  await waitFor(() => expect(context.entered()).toBe(1));
  act(() => useAuthStore.getState().setSession(replacementOperationsActor));
  // Another actor can legitimately load the same group key after cleanup.
  // Existing caller cache reset alone must not become mutation authorization.
  context.client.setQueryData(roomingKey, workspace);
  await act(async () => { context.release(); await rejected; });
  expect(operationsApi[row.name]).not.toHaveBeenCalled();
  expect(context.callbacks).toEqual([]);
});

it.each(cases)("preserves $name variables, callbacks and defaults after same-owner renewal", async row => {
  const context = setup(row);
  let pending!: Promise<unknown>;
  act(() => { pending = context.result.current.execute(); });
  await waitFor(() => expect(context.entered()).toBe(1));
  act(() => useAuthStore.getState().setSession({ ...operationsActor, full_name: "Profile renewed" }));
  await act(async () => { context.release(); await pending; });
  const method = vi.mocked(operationsApi[row.name]);
  expect(method).toHaveBeenCalledOnce();
  // Direct mutation functions receive TanStack context/owner trailing arguments;
  // their declared API argument prefix and actual transport bodies stay intact.
  expect(method.mock.calls[0].slice(0, row.expectedArgs.length)).toEqual(row.expectedArgs);
  expect(context.result.current.variables).toEqual(row.input);
  expect(context.callbacks).toEqual([
    { phase: "success", variables: row.input, context: undefined },
    { phase: "settled", variables: row.input, context: undefined },
  ]);
  act(() => context.result.current.reset());
  await waitFor(() => expect(context.result.current.isIdle).toBe(true));
  expect(context.result.current.variables).toBeUndefined();
});
