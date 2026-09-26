import { afterEach, describe, expect, it, vi } from "vitest";
import { refreshWithSingleConflictRetry } from "./refresh-attempt";

const conflict = { isAxiosError: true, response: { status: 409, data: { error: { code: "REFRESH_IN_PROGRESS" } } } };
afterEach(() => vi.useRealTimers());

describe("refresh lock conflict retry", () => {
  it("waits one second and retries once with the latest cookie", async () => {
    vi.useFakeTimers();
    const attempt = vi.fn().mockRejectedValueOnce(conflict).mockResolvedValueOnce({ status: "authenticated" });
    const result = refreshWithSingleConflictRetry(attempt);
    await vi.advanceTimersByTimeAsync(999);
    expect(attempt).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(await result).toEqual({ status: "authenticated" });
    expect(attempt).toHaveBeenCalledTimes(2);
  });
  it("does not loop on a repeated server conflict", async () => {
    vi.useFakeTimers();
    const attempt = vi.fn().mockRejectedValue(conflict);
    const result = expect(refreshWithSingleConflictRetry(attempt)).rejects.toBe(conflict);
    await vi.advanceTimersByTimeAsync(1_000); await result;
    expect(attempt).toHaveBeenCalledTimes(2);
  });
  it.each([401, 403, 500, 409])("propagates ordinary %i rejections without retry", async (status) => {
    const error = { isAxiosError: true, response: { status, data: { error: { code: "AUTH_REJECTED" } } } };
    const attempt = vi.fn().mockRejectedValue(error);
    await expect(refreshWithSingleConflictRetry(attempt)).rejects.toBe(error);
    expect(attempt).toHaveBeenCalledOnce();
  });
});
