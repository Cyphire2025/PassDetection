import axios from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { refreshAuthenticatedSession } from "./client";

const { clearSession } = vi.hoisted(() => ({ clearSession: vi.fn(async () => undefined) }));
vi.mock("@/stores/auth.store", () => ({ useAuthStore: { getState: () => ({ clearSession }) } }));
vi.mock("@/features/auth/services/refresh-coordinator", () => ({ readRefreshEpoch: () => "test", runCoordinatedRefresh: (_epoch: string, attempt: () => Promise<void>) => attempt() }));

beforeEach(() => clearSession.mockClear());
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe("dashboard refresh integration", () => {
  it("expires pre-migration credentials through the normal sign-in cleanup without refresh recursion", async () => {
    const post = vi.spyOn(axios, "post").mockRejectedValue({ isAxiosError: true, response: { status: 401, data: { error: { code: "TOKEN_REVOKED" } } } });
    await expect(refreshAuthenticatedSession()).rejects.toMatchObject({ code: "AUTH_SESSION_EXPIRED" });
    expect(post).toHaveBeenCalledOnce();
    expect(clearSession).toHaveBeenCalledExactlyOnceWith("session_expired", { revokeServerSession: false });
  });
  it("preserves the browser session for a winning concurrent rotation", async () => {
    vi.useFakeTimers();
    const session = { status: "authenticated", user: { id: "synthetic" } };
    const post = vi.spyOn(axios, "post")
      .mockRejectedValueOnce({ isAxiosError: true, response: { status: 409, data: { error: { code: "REFRESH_IN_PROGRESS" } } } })
      .mockResolvedValueOnce({ data: session });
    const first = refreshAuthenticatedSession();
    const second = refreshAuthenticatedSession();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(await first).toEqual(session); expect(await second).toEqual(session);
    expect(post).toHaveBeenCalledTimes(2);
    expect(clearSession).not.toHaveBeenCalled();
  });
});
