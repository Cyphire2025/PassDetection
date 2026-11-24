
import { beforeEach, describe, expect, it, vi } from "vitest";

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));

vi.mock("@/lib/api/client", () => ({ default: client }));

import {
  operationsApi,
  type GroupAttendanceSummary,
} from "./operations.api";

const summary: GroupAttendanceSummary = {
  group_id: "group-1",
  group_name: "Enterprise group",
  revision: "a".repeat(32),
  sessions: [],
};

describe("bounded attendance and audit API contracts", () => {
  beforeEach(() => {
    client.get.mockReset();
    client.post.mockReset();
    client.put.mockReset();
  });

  it("preserves ordered client events in a bounded attendance batch", async () => {
    client.post.mockResolvedValue({
      data: {
        batch_id: "5b194e4c-4d2a-4fd5-b4cf-63c4b7fc6d2f",
        items: [],
      },
    });

    await operationsApi.scanMyAttendanceSessionBatch({
      sessionId: "session-1",
      batchId: "5b194e4c-4d2a-4fd5-b4cf-63c4b7fc6d2f",
      scans: [
        {
          clientEventId: "event-0001",
          qrPayload: `pdatt:${"a".repeat(43)}`,
          scannedAt: "2026-08-25T10:00:00.000Z",
        },
        {
          clientEventId: "event-0002",
          qrPayload: `pdatt:${"b".repeat(43)}`,
          scannedAt: "2026-08-25T10:00:01.000Z",
        },
      ],
    });

    expect(client.post).toHaveBeenCalledWith(
      "/api/v1/tour-operations/coordinator/sessions/session-1/scan/batch",
      {
        batch_id: "5b194e4c-4d2a-4fd5-b4cf-63c4b7fc6d2f",
        scans: [
          {
            client_event_id: "event-0001",
            qr_payload: `pdatt:${"a".repeat(43)}`,
            scanned_at: "2026-08-25T10:00:00.000Z",
          },
          {
            client_event_id: "event-0002",
            qr_payload: `pdatt:${"b".repeat(43)}`,
            scanned_at: "2026-08-25T10:00:01.000Z",
          },
        ],
      },
      {},
    );
  });

  it("carries the captured queue owner as transport metadata without adding it to scan payloads", async () => {
    client.post.mockResolvedValue({ data: { status: "accepted", items: [] } });
    await operationsApi.scanMyAttendanceSession({
      sessionId: "session-1", qrPayload: "private-qr", clientEventId: "event-0001", expectedOwnerUserId: "owner-a",
    });
    await operationsApi.scanMyAttendanceSessionBatch({
      sessionId: "session-1", batchId: "batch-1", scans: [], expectedOwnerUserId: "owner-a",
    });
    for (const [, payload, config] of client.post.mock.calls) {
      expect(config).toEqual({ expectedOwnerUserId: "owner-a" });
      expect(payload).not.toHaveProperty("expectedOwnerUserId");
      expect(payload).not.toHaveProperty("expected_owner_user_id");
    }
  });

  it("binds count-only closeout publication to its captured queue owner", async () => {
    const checkpoint = { pending_count: 1, sending_count: 0, retryable_count: 0, needs_review_count: 0, unreviewed_rejected_count: 0, oldest_pending_age_seconds: 20 };
    client.put.mockResolvedValue({ data: { ...checkpoint, reported_at: "2026-10-30T10:00:00Z" } });
    await operationsApi.publishMyAttendanceCloseoutCheckpoint({
      groupId: "group-a", sessionId: "session-a", checkpoint, expectedOwnerUserId: "owner-a",
    });
    expect(client.put).toHaveBeenCalledWith(expect.any(String), checkpoint, { expectedOwnerUserId: "owner-a" });
  });

  it("reuses an unchanged summary through ETag without decoding a roster", async () => {
    const controller = new AbortController();
    client.get.mockResolvedValue({ status: 304, data: null });

    const result = await operationsApi.groupAttendanceSummary({
      groupId: "group-1",
      previous: summary,
      signal: controller.signal,
    });

    expect(result).toBe(summary);
    expect(client.get).toHaveBeenCalledWith(
      "/api/v1/tour-operations/groups/group-1/attendance/summary",
      expect.objectContaining({
        headers: { "If-None-Match": `"${summary.revision}"` },
        signal: controller.signal,
      }),
    );
    const config = client.get.mock.calls[0][1];
    expect(config.validateStatus(200)).toBe(true);
    expect(config.validateStatus(304)).toBe(true);
    expect(config.validateStatus(409)).toBe(false);
  });

  it("passes revision, keyset cursor, search, bound, and abort signal to missing pages", async () => {
    const controller = new AbortController();
    client.get.mockResolvedValue({
      data: {
        session_id: "session-1",
        revision: "b".repeat(32),
        items: [],
        has_more: false,
        next_cursor: null,
        page_size: 50,
      },
    });

    await operationsApi.groupAttendanceMissingPassengers({
      groupId: "group-1",
      sessionId: "session-1",
      revision: "b".repeat(32),
      cursor: "passenger-cursor",
      search: "Passenger",
      limit: 50,
      signal: controller.signal,
    });

    expect(client.get).toHaveBeenCalledWith(
      "/api/v1/tour-operations/groups/group-1/attendance/sessions/session-1/missing",
      {
        params: {
          revision: "b".repeat(32),
          cursor: "passenger-cursor",
          search: "Passenger",
          limit: 50,
        },
        signal: controller.signal,
      },
    );
  });

  it("passes audit filters and cancellation through cursor pages", async () => {
    const controller = new AbortController();
    client.get.mockResolvedValue({
      data: {
        items: [],
        has_more: false,
        next_cursor: null,
        incomplete: false,
        page_size: 50,
      },
    });

    await operationsApi.auditLogPage({
      filters: { result: "blocked", agency_id: "agency-1" },
      cursor: "cursor-1",
      signal: controller.signal,
    });

    expect(client.get).toHaveBeenCalledWith(
      "/api/v1/audit-logs/page",
      {
        params: {
          result: "blocked",
          agency_id: "agency-1",
          cursor: "cursor-1",
          page_size: 50,
        },
        signal: controller.signal,
      },
    );
  });
});
