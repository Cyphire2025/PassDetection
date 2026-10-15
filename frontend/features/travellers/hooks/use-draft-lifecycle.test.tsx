import { StrictMode, useRef } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDraftImageLifecycle } from "./use-draft-image-lifecycle";
import { useDraftInitialization } from "./use-draft-initialization";
import { useDraftPolling } from "./use-draft-polling";

const view = { id: "draft", revision: 4, status: "active", documents: [{ id: "image" }] };
const message = (cause: unknown) => String(cause);
beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.useRealTimers());

describe("private draft visit lifecycle", () => {
  it("shares the initial POST during StrictMode replay and aborts only on actual unmount", async () => {
    let finish!: (value: typeof view) => void;
    const load = vi.fn<(signal: AbortSignal) => Promise<typeof view>>(() => new Promise<typeof view>((resolve) => { finish = resolve; }));
    const receive = vi.fn(), pending = vi.fn(), report = vi.fn();
    const hook = renderHook(() => { const controller = useRef<AbortController | null>(null); useDraftInitialization(load, receive, controller, pending, report, message, "member"); }, { wrapper: StrictMode });
    expect(load).toHaveBeenCalledOnce(); const signal = load.mock.calls[0][0] as AbortSignal;
    await act(async () => { finish(view); });
    expect(signal.aborted).toBe(false); expect(receive).toHaveBeenCalledOnce();
    hook.unmount(); await waitFor(() => expect(signal.aborted).toBe(true));
  });

  it("rejects the previous member's late initialization response", async () => {
    const finish: Array<(value: typeof view) => void> = [];
    const load = vi.fn(() => new Promise<typeof view>((resolve) => finish.push(resolve)));
    const receive = vi.fn(), pending = vi.fn(), report = vi.fn();
    const hook = renderHook(({ member }) => { const controller = useRef<AbortController | null>(null); useDraftInitialization(load, receive, controller, pending, report, message, member); }, { initialProps: { member: "first" } });
    hook.rerender({ member: "second" });
    await act(async () => { finish[1]({ ...view, id: "second" }); finish[0]({ ...view, id: "first" }); });
    expect(receive).toHaveBeenCalledOnce(); expect(receive.mock.calls[0][0].id).toBe("second");
  });

  it("does not re-adopt the old initial payload after the form already received newer uploads", async () => {
    const load = vi.fn().mockResolvedValue(view), receive = vi.fn(), pending = vi.fn(), report = vi.fn();
    const hook = renderHook(({ loader, receiver }) => { const controller = useRef<AbortController | null>(null); useDraftInitialization(loader, receiver, controller, pending, report, message, "same-visit"); }, { initialProps: { loader: load, receiver: receive } });
    await waitFor(() => expect(receive).toHaveBeenCalledOnce());
    const nextLoad = vi.fn().mockResolvedValue({ ...view, documents: [] }), nextReceive = vi.fn();
    hook.rerender({ loader: nextLoad, receiver: nextReceive }); await act(async () => {});
    expect(nextLoad).not.toHaveBeenCalled(); expect(nextReceive).not.toHaveBeenCalled();
  });

  it("keeps images while hidden, heartbeats while visible, and discards on pagehide", async () => {
    vi.useFakeTimers(); const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    const api = { activity: vi.fn().mockResolvedValue({ images_present: true, presence_recorded: true, heartbeat_after_seconds: 60 }), discard: vi.fn().mockResolvedValue(undefined) };
    const cancel = vi.fn(), resume = vi.fn();
    renderHook(() => { const current = useRef(view); return useDraftImageLifecycle(current, view, api, cancel, resume); });
    await act(async () => {}); expect(api.activity).toHaveBeenCalledOnce();
    hidden.mockReturnValue(true); act(() => document.dispatchEvent(new Event("visibilitychange")));
    await act(() => vi.advanceTimersByTimeAsync(120_000));
    expect(api.activity).toHaveBeenCalledOnce(); expect(api.discard).not.toHaveBeenCalled();
    hidden.mockReturnValue(false); await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    expect(api.activity).toHaveBeenCalledTimes(2);
    await act(async () => window.dispatchEvent(new Event("pagehide")));
    expect(cancel).toHaveBeenCalledOnce(); expect(api.discard).toHaveBeenCalledWith(4, undefined, true);
    hidden.mockRestore();
  });

  it("explicit leave clears files once and submitted drafts never discard", async () => {
    const api = { activity: vi.fn().mockResolvedValue({ images_present: true, presence_recorded: true, heartbeat_after_seconds: 60 }), discard: vi.fn().mockResolvedValue({ ...view, revision: 5, documents: [] }) };
    const cancel = vi.fn(), resume = vi.fn();
    const hook = renderHook(() => { const current = useRef(view); const discard = useDraftImageLifecycle(current, view, api, cancel, resume); return { discard, current }; });
    await act(async () => { const result = await hook.result.current.discard(); hook.result.current.current.current = result!; });
    hook.unmount(); expect(api.discard).toHaveBeenCalledOnce();
    api.discard.mockClear(); const submitted = { ...view, status: "submitted" };
    const complete = renderHook(() => { const current = useRef(submitted); return useDraftImageLifecycle(current, submitted, api, cancel, resume); });
    complete.unmount(); expect(api.discard).not.toHaveBeenCalled();
  });

  it("does not discard staged images during StrictMode or callback replay", async () => {
    const api = { activity: vi.fn().mockResolvedValue({ images_present: true, presence_recorded: true, heartbeat_after_seconds: 60 }), discard: vi.fn().mockResolvedValue(undefined) };
    const cancel = vi.fn(); const firstResume = vi.fn();
    const hook = renderHook(({ resume }) => { const current = useRef(view); return useDraftImageLifecycle(current, view, api, cancel, resume, "same-visit"); }, { wrapper: StrictMode, initialProps: { resume: firstResume } });
    await act(async () => {}); expect(api.discard).not.toHaveBeenCalled();
    hook.rerender({ resume: vi.fn() }); await act(async () => {}); expect(api.discard).not.toHaveBeenCalled();
    hook.unmount(); await waitFor(() => expect(api.discard).toHaveBeenCalledOnce());
  });

  it("refreshes stale image readiness when the server reports an expired visit's images are gone", async () => {
    const api = { activity: vi.fn().mockResolvedValue({ images_present: false, presence_recorded: false, heartbeat_after_seconds: 60 }), discard: vi.fn().mockResolvedValue(undefined) };
    const cancel = vi.fn(), resume = vi.fn(), refresh = vi.fn().mockResolvedValue(undefined);
    renderHook(() => { const current = useRef(view); return useDraftImageLifecycle(current, view, api, cancel, resume, "visit", refresh); });
    await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
    expect(api.discard).not.toHaveBeenCalled();
  });
});

describe("bounded draft polling", () => {
  it("does not build a backlog while a check is slow and stops after unmount", async () => {
    vi.useFakeTimers(); let finish!: () => void;
    const refresh = vi.fn(() => new Promise<void>((resolve) => { finish = resolve; })), report = vi.fn();
    const hook = renderHook(() => useDraftPolling(true, refresh, report));
    await act(() => vi.advanceTimersByTimeAsync(60_000)); expect(refresh).toHaveBeenCalledOnce();
    await act(async () => { finish(); }); await act(() => vi.advanceTimersByTimeAsync(4_000)); expect(refresh).toHaveBeenCalledTimes(2);
    hook.unmount(); await act(async () => { finish(); }); await act(() => vi.advanceTimersByTimeAsync(60_000)); expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("backs off for five minutes, caps thirty checks, and resets for a replacement", async () => {
    vi.useFakeTimers(); const refresh = vi.fn().mockResolvedValue(undefined), report = vi.fn();
    const hook = renderHook(({ cycle }) => useDraftPolling(true, refresh, report, cycle), { initialProps: { cycle: "first-image" } });
    await act(() => vi.advanceTimersByTimeAsync(120_000)); expect(refresh.mock.calls.length).toBeLessThan(30); expect(report).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(240_000)); expect(refresh).toHaveBeenCalledTimes(30); expect(report).toHaveBeenCalledOnce();
    hook.rerender({ cycle: "replacement-image" }); await act(() => vi.advanceTimersByTimeAsync(2_000)); expect(refresh).toHaveBeenCalledTimes(31);
  });
});
