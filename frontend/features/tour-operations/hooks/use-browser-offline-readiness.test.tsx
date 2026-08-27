import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BrowserOfflineReadinessState } from "../services/browser-offline-readiness";
import { useBrowserOfflineReadiness } from "./use-browser-offline-readiness";

const mocks = vi.hoisted(() => ({
  resolve: vi.fn(),
}));

vi.mock("../services/browser-offline-readiness", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../services/browser-offline-readiness")>()),
  resolveBrowserOfflineReadiness: mocks.resolve,
}));

const GROUP_A = "11111111-1111-4111-8111-111111111111";
const GROUP_B = "22222222-2222-4222-8222-222222222222";
const SESSION_ID = "33333333-3333-4333-8333-333333333333";

function ready(groupId: string): Exclude<BrowserOfflineReadinessState, { status: "checking" }> {
  return {
    checkedAt: "2026-08-25T08:00:00.000Z",
    groupId,
    sessionId: SESSION_ID,
    status: "ready",
    validUntil: "2026-08-25T08:05:00.000Z",
  };
}

describe("useBrowserOfflineReadiness", () => {
  beforeEach(() => {
    mocks.resolve.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("checks cached signed readiness during an offline reload without refreshing", async () => {
    mocks.resolve.mockResolvedValue(ready(GROUP_A));

    const { result } = renderHook(() => useBrowserOfflineReadiness({
      enabled: true,
      groupId: GROUP_A,
      isOnline: false,
      refreshWhenOnline: false,
      sessionId: SESSION_ID,
    }));

    expect(result.current.status).toBe("checking");
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(mocks.resolve).toHaveBeenCalledOnce();
    expect(mocks.resolve).toHaveBeenCalledWith(expect.objectContaining({
      groupId: GROUP_A,
      refreshOnline: false,
      sessionId: SESSION_ID,
    }));
  });

  it("does not publish an old group's late readiness result after a scope change", async () => {
    let releaseGroupA: ((value: ReturnType<typeof ready>) => void) | undefined;
    mocks.resolve.mockImplementation(({ groupId }: { groupId: string }) => {
      if (groupId === GROUP_A) {
        return new Promise<ReturnType<typeof ready>>((resolve) => {
          releaseGroupA = resolve;
        });
      }
      return Promise.resolve(ready(GROUP_B));
    });

    const { result, rerender } = renderHook(
      ({ groupId }) => useBrowserOfflineReadiness({
        enabled: true,
        groupId,
        isOnline: false,
        refreshWhenOnline: false,
        sessionId: SESSION_ID,
      }),
      { initialProps: { groupId: GROUP_A } },
    );

    rerender({ groupId: GROUP_B });
    await waitFor(() => expect(result.current).toMatchObject({
      groupId: GROUP_B,
      status: "ready",
    }));
    await act(async () => {
      releaseGroupA?.(ready(GROUP_A));
      await Promise.resolve();
    });
    expect(result.current).toMatchObject({ groupId: GROUP_B, status: "ready" });
  });
});
