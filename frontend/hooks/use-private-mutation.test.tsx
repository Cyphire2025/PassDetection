import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { usePrivateMutation } from "./use-private-mutation";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
const actor = (id: string) => useAuthStore.setState({ user: { id, role: "agency_admin" } as User });
const clients: QueryClient[] = [];
function wrapper(cache?: MutationCache) {
  const client = new QueryClient({ mutationCache: cache, defaultOptions: { mutations: { retry: false } } });
  clients.push(client);
  return { client, wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> };
}
beforeEach(() => actor("initial-actor"));
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

it("captures the caller before a global onMutate await and refuses queued dispatch after an actor change", async () => {
  const start = deferred<void>();
  const entered = vi.fn();
  const transport = vi.fn(async () => "saved");
  const context = wrapper(new MutationCache({ onMutate: async () => { entered(); await start.promise; } }));
  const { result } = renderHook(() => usePrivateMutation({ mutationFn: transport }), context);
  let operation!: Promise<string>;
  act(() => { operation = result.current.mutateAsync(); });
  const rejected = expect(operation).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
  await waitFor(() => expect(entered).toHaveBeenCalledOnce());
  actor("replacement-actor");
  await act(async () => { start.resolve(); await rejected; });
  expect(transport).not.toHaveBeenCalled();
  await waitFor(() => expect(result.current.isError).toBe(true));
});

it("guards the local onMutate await before calling transport", async () => {
  const transport = vi.fn(async () => "saved");
  const { result } = renderHook(() => usePrivateMutation({ mutationFn: transport, onMutate: async () => { actor("replacement-actor"); } }), wrapper());
  await act(async () => { await expect(result.current.mutateAsync()).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" }); });
  expect(transport).not.toHaveBeenCalled();
});

it("preserves variables, custom context, local and per-call success callbacks, flags and reset", async () => {
  const original = { id: "original" }, custom = { previous: "snapshot" };
  const success = vi.fn(), settled = vi.fn(), callSuccess = vi.fn(), callSettled = vi.fn();
  const context = wrapper();
  const { result } = renderHook(() => usePrivateMutation({
    mutationFn: async (variables: typeof original, mutationContext, owner) => {
      expect(variables).toBe(original); expect(mutationContext.client).toBe(context.client);
      expect(owner.requestConfig).toEqual({ expectedOwnerUserId: "initial-actor", expectedAuthorityKey: '["initial-actor","agency_admin",null]' });
      return "saved";
    }, onMutate: (variables, mutationContext) => { expect(variables).toBe(original); expect(mutationContext.client).toBe(context.client); return custom; },
    onSuccess: success, onSettled: settled,
  }), context);
  await act(async () => { await result.current.mutateAsync(original, { onSuccess: callSuccess, onSettled: callSettled }); });
  await waitFor(() => expect(result.current.variables).toBe(original)); expect(result.current.context).toBe(custom); expect(result.current.isSuccess).toBe(true);
  expect(success).toHaveBeenCalledWith("saved", original, custom, expect.objectContaining({ client: context.client }), expect.objectContaining({ assertCurrent: expect.any(Function) }));
  expect(callSuccess).toHaveBeenCalledWith("saved", original, custom, expect.objectContaining({ client: context.client }));
  expect(settled.mock.calls[0]?.slice(0, 3)).toEqual(["saved", null, original]);
  expect(callSettled.mock.calls[0]?.slice(0, 3)).toEqual(["saved", null, original]);
  act(() => result.current.reset());
  await waitFor(() => expect(result.current.isIdle).toBe(true)); expect(result.current.variables).toBeUndefined();
});

it("preserves original variables and context in ordinary error and settled callbacks", async () => {
  const original = { id: "original" }, custom = { previous: "snapshot" }, failure = new Error("Synthetic failure");
  const onError = vi.fn(), onSettled = vi.fn(), callError = vi.fn(), callSettled = vi.fn();
  const { result } = renderHook(() => usePrivateMutation({
    mutationFn: async (variables: typeof original) => { expect(variables).toBe(original); throw failure; }, onMutate: () => custom, onError, onSettled,
  }), wrapper());
  await act(async () => { await expect(result.current.mutateAsync(original, { onError: callError, onSettled: callSettled })).rejects.toBe(failure); });
  expect(onError.mock.calls[0]?.slice(0, 3)).toEqual([failure, original, custom]);
  expect(callError.mock.calls[0]?.slice(0, 3)).toEqual([failure, original, custom]);
  expect(onSettled.mock.calls[0]?.slice(0, 4)).toEqual([undefined, failure, original, custom]);
  expect(callSettled.mock.calls[0]?.slice(0, 4)).toEqual([undefined, failure, original, custom]);
  await waitFor(() => expect(result.current.isError).toBe(true));
});

it("keeps overlapping invocation owners separate and suppresses stale callbacks", async () => {
  const old = deferred<string>();
  const success = vi.fn();
  const { result } = renderHook(() => usePrivateMutation({
    mutationFn: (id: string, _context, owner) => {
      expect(owner.requestConfig.expectedOwnerUserId).toBe(id === "old" ? "initial-actor" : "replacement-actor");
      return id === "old" ? old.promise : Promise.resolve("new result");
    }, onSuccess: success,
  }), wrapper());
  let previous!: Promise<string>;
  act(() => { previous = result.current.mutateAsync("old"); });
  const rejected = expect(previous).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
  await act(async () => undefined);
  actor("replacement-actor");
  await act(async () => { expect(await result.current.mutateAsync("new")).toBe("new result"); old.resolve("old private result"); await rejected; });
  expect(success).toHaveBeenCalledOnce(); expect(success.mock.calls[0]?.[0]).toBe("new result");
  await waitFor(() => expect(result.current.variables).toBe("new"));
});

it("fails closed for a missing initiating actor while retaining normal mutation error state", async () => {
  useAuthStore.setState({ user: null });
  const transport = vi.fn(async () => "saved");
  const { result } = renderHook(() => usePrivateMutation({ mutationFn: transport }), wrapper());
  await act(async () => { await expect(result.current.mutateAsync()).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" }); });
  expect(transport).not.toHaveBeenCalled(); await waitFor(() => expect(result.current.isError).toBe(true));
});

it("keeps mutate void-returning while forwarding its ordinary failure callbacks", async () => {
  const failure = new Error("Synthetic failure"), original = { id: "original" };
  const onError = vi.fn();
  const { result } = renderHook(() => usePrivateMutation({ mutationFn: async (variables: typeof original) => { expect(variables).toBe(original); throw failure; } }), wrapper());
  act(() => { expect(result.current.mutate(original, { onError })).toBeUndefined(); });
  await waitFor(() => expect(onError).toHaveBeenCalledWith(failure, original, undefined, expect.objectContaining({ client: expect.any(QueryClient) })));
  expect(result.current.error).toBe(failure);
});

it("rejects a formerly successful result if the account changes while awaiting global settled work", async () => {
  const context = wrapper(new MutationCache({ onSettled: async (_data, error) => { if (!error) actor("replacement-actor"); } }));
  const callSuccess = vi.fn(), callError = vi.fn(), callSettled = vi.fn();
  const { result } = renderHook(() => usePrivateMutation({ mutationFn: async () => "private result" }), context);
  await act(async () => {
    await expect(result.current.mutateAsync(undefined, { onSuccess: callSuccess, onError: callError, onSettled: callSettled }))
      .rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
  });
  expect(callSuccess).not.toHaveBeenCalled(); expect(callError).not.toHaveBeenCalled(); expect(callSettled).not.toHaveBeenCalled();
  await waitFor(() => expect(result.current.isError).toBe(true));
});
