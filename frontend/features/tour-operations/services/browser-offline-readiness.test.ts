import { describe, expect, it, vi } from "vitest";

import { BrowserOfflineAuthorizationError } from "./browser-offline-authorization";
import {
  BROWSER_OFFLINE_READINESS_RECHECK_MS,
  browserOfflineReadinessAllowsCapture,
  browserOfflineReadinessRecheckDelay,
  resolveBrowserOfflineReadiness,
  type BrowserOfflineReadinessState,
} from "./browser-offline-readiness";

const GROUP_ID = "11111111-1111-4111-8111-111111111111";
const SESSION_ID = "22222222-2222-4222-8222-222222222222";
const EVIDENCE = {
  checkedAt: "2026-08-25T08:00:00.000Z",
  groupId: GROUP_ID,
  sessionId: SESSION_ID,
  validUntil: "2026-08-25T08:05:00.000Z",
} as const;

describe("browser offline readiness", () => {
  it("accepts a locally valid signed authorization while already offline", async () => {
    const refresh = vi.fn(async () => undefined as never);
    const check = vi.fn(async () => EVIDENCE);

    await expect(resolveBrowserOfflineReadiness({
      dependencies: { check, refresh },
      groupId: GROUP_ID,
      refreshOnline: false,
      sessionId: SESSION_ID,
    })).resolves.toEqual({ ...EVIDENCE, status: "ready" });
    expect(refresh).not.toHaveBeenCalled();
    expect(check).toHaveBeenCalledWith({ groupId: GROUP_ID, sessionId: SESSION_ID });
  });

  it("keeps valid cached readiness after a transient online refresh failure", async () => {
    const refresh = vi.fn(async () => {
      throw new TypeError("network unavailable");
    });
    const check = vi.fn(async () => EVIDENCE);

    await expect(resolveBrowserOfflineReadiness({
      dependencies: { check, refresh },
      groupId: GROUP_ID,
      refreshOnline: true,
      sessionId: SESSION_ID,
    })).resolves.toMatchObject({ status: "ready" });
    expect(refresh).toHaveBeenCalledOnce();
    expect(check).toHaveBeenCalledOnce();
  });

  it("fails closed when local activity-window verification rejects the cache", async () => {
    const refresh = vi.fn(async () => undefined as never);
    const check = vi.fn(async () => {
      throw new BrowserOfflineAuthorizationError("ACTIVITY_OUTSIDE_WINDOW");
    });

    await expect(resolveBrowserOfflineReadiness({
      dependencies: { check, refresh },
      groupId: GROUP_ID,
      refreshOnline: true,
      sessionId: SESSION_ID,
    })).resolves.toEqual({
      code: "ACTIVITY_OUTSIDE_WINDOW",
      groupId: GROUP_ID,
      sessionId: SESSION_ID,
      status: "unavailable",
    });
  });

  it("normalizes unexpected local storage or crypto failures without opening capture", async () => {
    const check = vi.fn(async () => {
      throw new Error("IndexedDB unavailable");
    });

    await expect(resolveBrowserOfflineReadiness({
      dependencies: {
        check,
        refresh: vi.fn(async () => undefined as never),
      },
      groupId: GROUP_ID,
      refreshOnline: false,
      sessionId: SESSION_ID,
    })).resolves.toMatchObject({
      code: "READINESS_CHECK_FAILED",
      status: "unavailable",
    });
  });

  it("rechecks on a bounded cadence and just after near-term trusted expiry", () => {
    expect(browserOfflineReadinessRecheckDelay(EVIDENCE))
      .toBe(BROWSER_OFFLINE_READINESS_RECHECK_MS);
    expect(browserOfflineReadinessRecheckDelay({
      ...EVIDENCE,
      validUntil: "2026-08-25T08:00:01.000Z",
    })).toBe(1_250);
    expect(browserOfflineReadinessRecheckDelay({
      ...EVIDENCE,
      checkedAt: "invalid",
    })).toBe(250);
  });

  it("allows online capture independently but requires ready evidence offline", () => {
    const checking: BrowserOfflineReadinessState = {
      groupId: GROUP_ID,
      sessionId: SESSION_ID,
      status: "checking",
    };
    const ready: BrowserOfflineReadinessState = { ...EVIDENCE, status: "ready" };

    expect(browserOfflineReadinessAllowsCapture(true, checking)).toBe(true);
    expect(browserOfflineReadinessAllowsCapture(false, checking)).toBe(false);
    expect(browserOfflineReadinessAllowsCapture(false, ready)).toBe(true);
  });
});
