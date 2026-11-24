import type { ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import { mcpApi } from "../api/mcp.api";
import { mcpAdminFixture, permissionFixture } from "../utils/permissions.test-fixture";
import { permissionUpdate } from "../utils/permissions";
import { useMcpDeleteConnection, useMcpOperations, useMcpRequests, useMcpUpdatePermissions, useMcpUpdateReadAccess } from "./use-mcp";

vi.mock("../api/mcp.api", () => ({ mcpApi: {
  updatePermissions: vi.fn(), updateReadAccess: vi.fn(), deleteConnection: vi.fn(),
  operations: vi.fn(), requests: vi.fn(),
} }));
const owner = mcpAdminFixture({ id: "staff-a" });
const clients: QueryClient[] = [];
type Flow = "permissions" | "read" | "delete";
function mount(flow: Flow, onMutate?: () => Promise<void>) {
  const client = new QueryClient({ mutationCache: new MutationCache({ onMutate }),
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const view = renderHook(() => {
    const permissions = useMcpUpdatePermissions();
    const read = useMcpUpdateReadAccess();
    const remove = useMcpDeleteConnection();
    return () => flow === "permissions" ? permissions.mutateAsync(permissionUpdate(permissionFixture()))
      : flow === "read" ? read.mutateAsync({ expected_revision: 1, allowed_read_sections: ["all_groups"] })
      : remove.mutateAsync("selected-connection");
  }, { wrapper });
  return { ...view, client };
}
function request(flow: Flow) {
  return flow === "permissions" ? mcpApi.updatePermissions : flow === "read" ? mcpApi.updateReadAccess : mcpApi.deleteConnection;
}
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: owner, isAuthenticated: true });
  vi.mocked(mcpApi.updatePermissions).mockResolvedValue(permissionFixture());
  vi.mocked(mcpApi.updateReadAccess).mockResolvedValue({ revision: 2 } as Awaited<ReturnType<typeof mcpApi.updateReadAccess>>);
  vi.mocked(mcpApi.deleteConnection).mockResolvedValue({ deleted: true });
});
afterEach(() => { clients.splice(0).forEach(client => client.clear()); vi.restoreAllMocks(); vi.useRealTimers(); });

it.each(["permissions", "read", "delete"] as const)("rejects an old %s intent after a global mutation pause crosses accounts", async flow => {
  let release!: () => void;
  const view = mount(flow, () => new Promise<void>(resolve => { release = resolve; }));
  let outcome!: Promise<unknown>;
  act(() => { outcome = view.result.current().catch(error => error); });
  await waitFor(() => expect(release).toBeTypeOf("function"));
  useAuthStore.setState({ user: { ...owner, id: "staff-b" } });
  await act(async () => { release(); expect(await outcome).toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" }); });
  expect(request(flow)).not.toHaveBeenCalled();
});

it.each(["permissions", "read"] as const)("does not dispatch %s after its query cancellation crosses accounts", async flow => {
  const view = mount(flow);
  let release!: () => void;
  vi.spyOn(view.client, "cancelQueries").mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve; }));
  let outcome!: Promise<unknown>;
  act(() => { outcome = view.result.current().catch(error => error); });
  await waitFor(() => expect(release).toBeTypeOf("function"));
  useAuthStore.setState({ user: { ...owner, id: "staff-b" } });
  await act(async () => { release(); expect(await outcome).toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" }); });
  expect(request(flow)).not.toHaveBeenCalled();
});

it.each([
  ["requests", 401], ["requests", 403], ["requests", 404],
  ["operations", 401], ["operations", 403], ["operations", 404],
] as const)("stops automatic private %s polling after %s and retains explicit recovery", async (flow, status) => {
  vi.useFakeTimers();
  const requests = { items: [], next_offset: null } satisfies Awaited<ReturnType<typeof mcpApi.requests>>;
  const operations = { items: [{ id: "queued-operation", operation: "export", workflow_id: "workflow",
    connection_id: "connection", status: "queued", progress: 0, stage: "queued", revision: 1,
    created_entities: [], created_at: "2026-10-30T00:00:00Z", updated_at: "2026-10-30T00:00:00Z",
    completed_at: null }], next_offset: null } satisfies Awaited<ReturnType<typeof mcpApi.operations>>;
  const request = vi.mocked(mcpApi[flow]);
  const denied = { status, code: "ACCESS_DENIED" };
  if (flow === "requests") vi.mocked(mcpApi.requests).mockResolvedValueOnce(requests).mockRejectedValue(denied);
  else vi.mocked(mcpApi.operations).mockResolvedValueOnce(operations).mockRejectedValue(denied);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const useFlowQuery = flow === "requests" ? useMcpRequests : useMcpOperations;
  const view = renderHook(() => useFlowQuery(0), { wrapper });
  try {
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(request).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(5_001); });
    expect(request).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(request).toHaveBeenCalledTimes(2);
    if (flow === "requests") vi.mocked(mcpApi.requests).mockResolvedValue(requests);
    else vi.mocked(mcpApi.operations).mockResolvedValue(operations);
    await act(async () => { expect((await view.result.current.refetch()).isSuccess).toBe(true); });
    expect(request).toHaveBeenCalledTimes(3);
  } finally { view.unmount(); }
});
