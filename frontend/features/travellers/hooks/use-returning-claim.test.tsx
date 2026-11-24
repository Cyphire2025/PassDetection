import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { returningApi } from "../api/returning.api";
import type { ClaimTransition, ReturningHistory } from "../types";
import { useReturningClaim } from "./use-returning-claim";

vi.mock("../api/returning.api", () => ({ returningApi: {
  start: vi.fn(), authorize: vi.fn(), passport: vi.fn(), candidates: vi.fn(), history: vi.fn(), requestOtp: vi.fn(),
} }));
const history = { display_name: "Verified synthetic traveller" } as ReturningHistory;
function deferred<T>() { let resolve!: (value: T) => void; return { promise: new Promise<T>(done => { resolve = done; }), resolve }; }
beforeEach(() => { vi.clearAllMocks(); vi.mocked(returningApi.history).mockResolvedValue(history); });

it("stops a repeated automatic authorization stage and permits an explicit retry", async () => {
  vi.mocked(returningApi.start).mockResolvedValue({ stage: "confirm" });
  let responses = 0;
  vi.mocked(returningApi.authorize).mockImplementation(async () => {
    if (++responses > 6) throw new Error("Synthetic repeated-stage stop prevents an unbounded baseline test");
    return { stage: "confirm" };
  });
  const { result } = renderHook(useReturningClaim);
  await act(() => result.current.start({ group_token: "synthetic-trip", method: "code", individual_code: "00019" }));
  expect(returningApi.authorize).toHaveBeenCalledOnce();
  expect(result.current.error).toMatch(/did not advance.*retry/i);
  expect(result.current.pending).toBe(false); expect(returningApi.history).not.toHaveBeenCalled();
  vi.mocked(returningApi.authorize).mockResolvedValue({ stage: "review" });
  await act(() => result.current.retryStage());
  expect(result.current.history).toBe(history); expect(result.current.error).toBeUndefined();
  expect(returningApi.history).toHaveBeenCalledExactlyOnceWith(expect.any(AbortSignal), "synthetic-trip");
});

it("bounds a nonadvancing passport identification response without revealing history", async () => {
  vi.mocked(returningApi.start).mockResolvedValue({ stage: "identify" });
  let responses = 0;
  vi.mocked(returningApi.passport).mockImplementation(async () => {
    if (++responses > 6) throw new Error("Synthetic repeated-stage stop");
    return { stage: "identify" };
  });
  const { result } = renderHook(useReturningClaim);
  await act(() => result.current.start({ group_token: "synthetic-trip", method: "passport", passport_number: "TEST0001" }));
  expect(returningApi.passport).toHaveBeenCalledExactlyOnceWith({}, expect.any(AbortSignal));
  expect(result.current.error).toMatch(/did not advance.*retry/i); expect(returningApi.history).not.toHaveBeenCalled();
});

it("preserves a progressing recovery chain and current group history request", async () => {
  vi.mocked(returningApi.start).mockResolvedValue({ stage: "confirm" });
  vi.mocked(returningApi.authorize).mockResolvedValueOnce({ stage: "recovery" }).mockResolvedValueOnce({ stage: "review" });
  const { result } = renderHook(useReturningClaim);
  await act(() => result.current.start({ group_token: "synthetic-trip", method: "code", individual_code: "00019" }));
  expect(returningApi.authorize).toHaveBeenCalledTimes(2); expect(result.current.error).toBeUndefined();
  expect(result.current.history).toBe(history); expect(result.current.transition?.stage).toBe("review");
});

it("does not begin an OTP request after an abandoned claim start resolves", async () => {
  const start = deferred<ClaimTransition>(); vi.mocked(returningApi.start).mockReturnValue(start.promise);
  vi.mocked(returningApi.requestOtp).mockResolvedValue({ expires_in_seconds: 300, resend_after_seconds: 30 });
  const { result, unmount } = renderHook(useReturningClaim);
  let operation!: Promise<void>;
  act(() => { operation = result.current.start({ group_token: "synthetic-trip", method: "phone", phone_number: "+12025550100" }); });
  const signal = vi.mocked(returningApi.start).mock.calls[0][1]!; unmount(); expect(signal.aborted).toBe(true);
  await act(async () => { start.resolve({ stage: "contact" }); await operation; });
  expect(returningApi.requestOtp).not.toHaveBeenCalled(); expect(returningApi.history).not.toHaveBeenCalled();
});

it("does not read private history after an abandoned authorization response resolves", async () => {
  const authorization = deferred<ClaimTransition>();
  vi.mocked(returningApi.start).mockResolvedValue({ stage: "confirm" }); vi.mocked(returningApi.authorize).mockReturnValue(authorization.promise);
  const { result, unmount } = renderHook(useReturningClaim); let operation!: Promise<void>;
  await act(async () => { operation = result.current.start({ group_token: "synthetic-trip", method: "code", individual_code: "00019" }); });
  expect(returningApi.authorize).toHaveBeenCalledOnce(); unmount();
  await act(async () => { authorization.resolve({ stage: "review" }); await operation; });
  expect(returningApi.history).not.toHaveBeenCalled();
});
