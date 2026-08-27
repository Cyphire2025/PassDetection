import { describe, expect, it } from "vitest";
import {
  DASHBOARD_REALTIME_PATH,
  dashboardRealtimeReconnectDelayMs,
  dashboardRealtimeQueryPrefixes,
  dashboardRealtimeWebSocketUrl,
  parseDashboardRealtimeServerFrame,
  shouldInvalidateAttendanceFromRealtime,
} from "./dashboard-realtime";

describe("dashboard realtime protocol", () => {
  it("builds only a same-origin cookie WebSocket URL without query credentials", () => {
    expect(dashboardRealtimeWebSocketUrl({ protocol: "https:", host: "app.example.test" }))
      .toBe(`wss://app.example.test${DASHBOARD_REALTIME_PATH}`);
    expect(dashboardRealtimeWebSocketUrl({ protocol: "http:", host: "127.0.0.1:3000" }))
      .toBe(`ws://127.0.0.1:3000${DASHBOARD_REALTIME_PATH}`);
    expect(dashboardRealtimeWebSocketUrl({ protocol: "file:", host: "" })).toBeNull();
    expect(dashboardRealtimeWebSocketUrl({ protocol: "https:", host: "evil.test/path" }))
      .toBeNull();
  });

  it("accepts the exact ready, heartbeat, and sync-hint server frames", () => {
    expect(parseDashboardRealtimeServerFrame(JSON.stringify({
      type: "ready",
      heartbeat_seconds: 20,
      idle_timeout_seconds: 65,
    }))).toEqual(expect.objectContaining({ type: "ready", heartbeat_seconds: 20 }));
    expect(parseDashboardRealtimeServerFrame('{"type":"heartbeat"}'))
      .toEqual({ type: "heartbeat" });
    const hint = parseDashboardRealtimeServerFrame(JSON.stringify({
      type: "sync_hint",
      trip_id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa2",
      cursor: 42,
      invalidation: "attendance",
    }));
    expect(hint).toEqual(expect.objectContaining({ type: "sync_hint", cursor: 42 }));
    expect(hint && shouldInvalidateAttendanceFromRealtime(hint)).toBe(true);
  });

  it("rejects oversized, extended, malformed, unsafe, and unrelated frames", () => {
    expect(parseDashboardRealtimeServerFrame('{"type":"heartbeat","token":"secret"}')).toBeNull();
    expect(parseDashboardRealtimeServerFrame(JSON.stringify({
      type: "sync_hint",
      trip_id: "not-a-uuid",
      cursor: 1,
      invalidation: "attendance",
    }))).toBeNull();
    expect(parseDashboardRealtimeServerFrame(JSON.stringify({
      type: "sync_hint",
      trip_id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa2",
      cursor: Number.MAX_SAFE_INTEGER + 1,
      invalidation: "attendance",
    }))).toBeNull();
    expect(parseDashboardRealtimeServerFrame(`{"type":"heartbeat","padding":"${"x".repeat(1_024)}"}`))
      .toBeNull();
    const documents = parseDashboardRealtimeServerFrame(JSON.stringify({
      type: "sync_hint",
      trip_id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa2",
      cursor: 43,
      invalidation: "documents",
    }));
    expect(documents && shouldInvalidateAttendanceFromRealtime(documents)).toBe(false);
  });

  it("maps non-attendance hints to bounded canonical query families", () => {
    const documents = parseDashboardRealtimeServerFrame(JSON.stringify({
      type: "sync_hint",
      trip_id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa2",
      cursor: 43,
      invalidation: "documents",
    }));
    expect(documents && dashboardRealtimeQueryPrefixes(documents)).toEqual([
      ["document-distribution"],
      ["gc-app"],
    ]);

    const all = parseDashboardRealtimeServerFrame(JSON.stringify({
      type: "sync_hint",
      trip_id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa2",
      cursor: 44,
      invalidation: "all",
    }));
    expect(all && dashboardRealtimeQueryPrefixes(all)).toEqual(expect.arrayContaining([
      ["gc-app"],
    ]));

    const roster = parseDashboardRealtimeServerFrame(JSON.stringify({
      type: "sync_hint",
      trip_id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa2",
      cursor: 45,
      invalidation: "roster",
    }));
    expect(roster && dashboardRealtimeQueryPrefixes(roster)).toEqual(expect.arrayContaining([
      ["operations", "tour-operations", "groups", "019d2a5b-6357-7600-8ed3-98c5ca70bfa2"],
      ["operations", "rooming", "019d2a5b-6357-7600-8ed3-98c5ca70bfa2"],
      ["passports"],
      ["dashboard", "stats"],
    ]));

    expect(dashboardRealtimeQueryPrefixes({ type: "heartbeat" })).toEqual([]);
  });

  it("uses bounded exponential backoff and slows auth or policy failures", () => {
    expect(dashboardRealtimeReconnectDelayMs(0, 1013, 0)).toBe(1_000);
    expect(dashboardRealtimeReconnectDelayMs(10, 1013, 1)).toBe(35_000);
    expect(dashboardRealtimeReconnectDelayMs(0, 4401, 0)).toBe(30_000);
    expect(dashboardRealtimeReconnectDelayMs(0, 1008, 1)).toBe(35_000);
  });
});
