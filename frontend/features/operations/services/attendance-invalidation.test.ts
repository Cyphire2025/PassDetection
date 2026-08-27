import { describe, expect, it } from "vitest";
import {
  attendanceRepairIntervalMs,
  normalizeAttendanceInvalidationHint,
  stableJitterMs,
} from "./attendance-invalidation";

describe("attendance invalidation policy", () => {
  it("uses deterministic bounded jitter to avoid synchronized repair bursts", () => {
    const first = attendanceRepairIntervalMs({
      groupId: "group-1",
      accessScope: "session:user:agency:role",
      hasActiveSession: true,
    });
    const second = attendanceRepairIntervalMs({
      groupId: "group-1",
      accessScope: "session:user:agency:role",
      hasActiveSession: true,
    });

    expect(first).toBe(second);
    expect(first).toBeGreaterThanOrEqual(5_000);
    expect(first).toBeLessThanOrEqual(7_000);
    expect(attendanceRepairIntervalMs({
      groupId: "group-1",
      accessScope: "session:user:agency:role",
      hasActiveSession: false,
    })).toBeGreaterThanOrEqual(30_000);
  });

  it("rejects malformed cross-context messages before they can invalidate caches", () => {
    const valid = normalizeAttendanceInvalidationHint({
      groupId: "group-1",
      sessionId: "session-1",
      source: "queue-sync",
      occurredAt: "2026-08-25T10:30:00.000Z",
    });

    expect(valid).toEqual(expect.objectContaining({ groupId: "group-1", sessionId: "session-1" }));
    expect(normalizeAttendanceInvalidationHint({ ...valid, groupId: "" })).toBeNull();
    expect(normalizeAttendanceInvalidationHint({ ...valid, source: "untrusted" })).toBeNull();
    expect(normalizeAttendanceInvalidationHint({ ...valid, occurredAt: "not-a-date" })).toBeNull();
  });

  it("rejects invalid jitter bounds", () => {
    expect(() => stableJitterMs("seed", 10, 5)).toThrow(RangeError);
  });
});
