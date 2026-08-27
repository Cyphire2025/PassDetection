import { describe, expect, it } from "vitest";
import type { AttendanceScanBatchItemResponse } from "@/features/operations/api/operations.api";
import {
  attendanceBatchItemDisposition,
  isMatchingAttendanceBatchEnvelope,
} from "./attendance-batch-policy";

const counted: AttendanceScanBatchItemResponse = {
  client_event_id: "event-0001",
  outcome: "counted",
  retryable: false,
  scan: {
    session_id: "session-1",
    passenger_id: "passenger-1",
    passenger_name: "Passenger",
    status: "counted",
    message: "Counted",
    scanned_count: 1,
    assigned_count: 10,
  },
  error_code: null,
};

describe("attendance batch reconciliation policy", () => {
  it("accepts only an exact, unique response envelope", () => {
    const response = { batch_id: "batch-1", items: [counted] };
    expect(isMatchingAttendanceBatchEnvelope({
      response,
      expectedBatchId: "batch-1",
      expectedClientEventIds: ["event-0001"],
    })).toBe(true);
    expect(isMatchingAttendanceBatchEnvelope({
      response: { ...response, batch_id: "batch-2" },
      expectedBatchId: "batch-1",
      expectedClientEventIds: ["event-0001"],
    })).toBe(false);
    expect(isMatchingAttendanceBatchEnvelope({
      response: { ...response, items: [counted, counted] },
      expectedBatchId: "batch-1",
      expectedClientEventIds: ["event-0001", "event-0002"],
    })).toBe(false);
  });

  it("removes only explicit terminal successes", () => {
    expect(attendanceBatchItemDisposition(counted)).toBe("success");
    expect(attendanceBatchItemDisposition({ ...counted, retryable: true })).toBe("retry");
    expect(attendanceBatchItemDisposition({ ...counted, scan: null })).toBe("retry");
    expect(attendanceBatchItemDisposition(undefined)).toBe("retry");
  });

  it("quarantines only explicit non-retryable rejections", () => {
    expect(attendanceBatchItemDisposition({
      client_event_id: "event-0001",
      outcome: "rejected",
      retryable: false,
      scan: null,
      error_code: "ATTENDANCE_SCAN_IDEMPOTENCY_CONFLICT",
    })).toBe("terminal-rejection");
    expect(attendanceBatchItemDisposition({
      client_event_id: "event-0001",
      outcome: "rejected",
      retryable: true,
      scan: null,
      error_code: "DEPENDENCY_UNAVAILABLE",
    })).toBe("retry");
  });
});
