import type {
  AttendanceScanBatchItemResponse,
  AttendanceScanBatchResponse,
} from "@/features/operations/api/operations.api";

export type AttendanceBatchItemDisposition =
  | "success"
  | "terminal-rejection"
  | "retry";

export function isMatchingAttendanceBatchEnvelope({
  response,
  expectedBatchId,
  expectedClientEventIds,
}: {
  response: AttendanceScanBatchResponse;
  expectedBatchId: string;
  expectedClientEventIds: readonly string[];
}): boolean {
  if (response.batch_id !== expectedBatchId) return false;
  if (response.items.length !== expectedClientEventIds.length) return false;
  const responseIds = response.items.map((item) => item.client_event_id);
  if (new Set(responseIds).size !== responseIds.length) return false;
  const expectedIds = new Set(expectedClientEventIds);
  return responseIds.every((clientEventId) => expectedIds.has(clientEventId));
}

export function attendanceBatchItemDisposition(
  item: AttendanceScanBatchItemResponse | undefined,
): AttendanceBatchItemDisposition {
  if (
    item
    && item.retryable === false
    && (item.outcome === "counted" || item.outcome === "duplicate")
    && item.scan !== null
    && item.error_code === null
    && (item.scan.status === "counted" || item.scan.status === "duplicate")
  ) return "success";

  if (
    item
    && item.retryable === false
    && item.outcome === "rejected"
    && item.scan === null
    && typeof item.error_code === "string"
    && item.error_code.length > 0
  ) return "terminal-rejection";

  // Retryable server outcomes, missing items, and malformed/ambiguous response
  // shapes all preserve the durable queue row for a later reconciliation.
  return "retry";
}
