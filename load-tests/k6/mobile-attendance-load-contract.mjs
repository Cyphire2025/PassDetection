const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SIGNED_ATTENDANCE_QR_PATTERN = /^pdatt:[A-Za-z0-9_-]{43}$/;

export const CANONICAL_ATTENDANCE_LOAD = Object.freeze({
  coordinatorCount: 25,
  duplicatesPerCoordinator: 4,
  scansPerCoordinator: 32,
});

const SESSION_STATUS = new Set(["draft", "active", "completed", "cancelled"]);

function validNullableIsoDate(value) {
  return value === null || (
    typeof value === "string"
    && value.length >= 20
    && value.length <= 40
    && Number.isFinite(Date.parse(value))
  );
}

function validAccessToken(value) {
  return typeof value === "string"
    && value.length >= 32
    && value.length <= 8192
    && value === value.trim()
    && !/\s/.test(value);
}

function hasExactKeys(value, expected) {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length
    && actual.every((key, index) => key === wanted[index]);
}

/**
 * Validates the bounded, direct session-detail response used only for count
 * reconciliation. Identifiers and roster rows are never returned or included
 * in errors, tags, or metrics.
 */
export function validateAttendanceCountReconciliation(
  parsed,
  expectedSessionId,
  expectedAssignedCount,
  expectedScannedCount,
) {
  if (
    typeof expectedSessionId !== "string"
    || !UUID_PATTERN.test(expectedSessionId)
    || !Number.isSafeInteger(expectedAssignedCount)
    || expectedAssignedCount < 1
    || !Number.isSafeInteger(expectedScannedCount)
    || expectedScannedCount < 0
  ) {
    throw new Error("Attendance reconciliation expectations are invalid");
  }
  if (
    !parsed
    || typeof parsed !== "object"
    || Array.isArray(parsed)
    || !hasExactKeys(parsed, ["session", "missing", "next_cursor"])
    || !Array.isArray(parsed.missing)
    || parsed.missing.length > 1
    || !(parsed.next_cursor === null
      || (typeof parsed.next_cursor === "string" && parsed.next_cursor.length <= 256))
  ) {
    throw new Error("Attendance reconciliation response contract is invalid");
  }
  const summary = parsed.session;
  if (
    !summary
    || typeof summary !== "object"
    || Array.isArray(summary)
    || !hasExactKeys(summary, [
      "assigned_count",
      "completed_at",
      "id",
      "name",
      "scanned_count",
      "started_at",
      "status",
    ])
    || summary.id !== expectedSessionId.toLowerCase()
    || typeof summary.name !== "string"
    || summary.name.length < 2
    || summary.name.length > 160
    || !SESSION_STATUS.has(summary.status)
    || !Number.isSafeInteger(summary.assigned_count)
    || summary.assigned_count !== expectedAssignedCount
    || !Number.isSafeInteger(summary.scanned_count)
    || summary.scanned_count !== expectedScannedCount
    || !validNullableIsoDate(summary.started_at)
    || !validNullableIsoDate(summary.completed_at)
  ) {
    throw new Error("Attendance reconciliation count did not match the canonical event");
  }
  return Object.freeze({
    assignedCount: summary.assigned_count,
    scannedCount: summary.scanned_count,
    status: summary.status,
  });
}

/**
 * Validates an uncommitted, synthetic staging fixture without ever echoing a
 * token, QR bearer, trip, session, or event identifier into an error message.
 */
export function validateAttendanceLoadEntries(
  parsed,
  coordinatorCount,
  scansPerCoordinator,
  duplicatesPerCoordinator,
) {
  if (!Number.isSafeInteger(coordinatorCount) || coordinatorCount < 1 || coordinatorCount > 100) {
    throw new Error("The attendance coordinator count is invalid");
  }
  if (
    !Number.isSafeInteger(scansPerCoordinator)
    || scansPerCoordinator < 1
    || scansPerCoordinator > 1000
  ) {
    throw new Error("The attendance scan count is invalid");
  }
  if (
    !Number.isSafeInteger(duplicatesPerCoordinator)
    || duplicatesPerCoordinator < 0
    || duplicatesPerCoordinator > scansPerCoordinator
  ) {
    throw new Error("The deliberate duplicate count is invalid");
  }
  if (!Array.isArray(parsed) || parsed.length !== coordinatorCount) {
    throw new Error("MOBILE_ATTENDANCE_LOAD_DATA must contain the exact coordinator count");
  }

  const tokens = new Set();
  const eventIds = new Set();
  const signedQrs = new Set();
  return parsed.map((entry, entryIndex) => {
    if (
      !entry
      || typeof entry !== "object"
      || Array.isArray(entry)
      || !hasExactKeys(entry, ["access_token", "trip_id", "session_id", "actions"])
      || !validAccessToken(entry.access_token)
      || typeof entry.trip_id !== "string"
      || !UUID_PATTERN.test(entry.trip_id)
      || typeof entry.session_id !== "string"
      || !UUID_PATTERN.test(entry.session_id)
      || !Array.isArray(entry.actions)
      || entry.actions.length !== scansPerCoordinator
    ) {
      throw new Error(`MOBILE_ATTENDANCE_LOAD_DATA entry ${entryIndex} is invalid`);
    }
    if (tokens.has(entry.access_token)) {
      throw new Error(`MOBILE_ATTENDANCE_LOAD_DATA entry ${entryIndex} reuses a session`);
    }
    tokens.add(entry.access_token);

    const actions = entry.actions.map((action, actionIndex) => {
      if (
        !action
        || typeof action !== "object"
        || Array.isArray(action)
        || !hasExactKeys(action, [
          "client_event_id",
          "duplicate_client_event_id",
          "signed_qr",
        ])
        || typeof action.client_event_id !== "string"
        || !UUID_PATTERN.test(action.client_event_id)
        || (actionIndex < duplicatesPerCoordinator
          ? (typeof action.duplicate_client_event_id !== "string"
            || !UUID_PATTERN.test(action.duplicate_client_event_id))
          : action.duplicate_client_event_id !== null)
        || typeof action.signed_qr !== "string"
        || !SIGNED_ATTENDANCE_QR_PATTERN.test(action.signed_qr)
      ) {
        throw new Error(
          `MOBILE_ATTENDANCE_LOAD_DATA entry ${entryIndex} action ${actionIndex} is invalid`,
        );
      }
      if (eventIds.has(action.client_event_id) || signedQrs.has(action.signed_qr)) {
        throw new Error("MOBILE_ATTENDANCE_LOAD_DATA contains a duplicate synthetic action");
      }
      eventIds.add(action.client_event_id);
      if (action.duplicate_client_event_id !== null) {
        if (eventIds.has(action.duplicate_client_event_id)) {
          throw new Error("MOBILE_ATTENDANCE_LOAD_DATA contains a duplicate synthetic event identifier");
        }
        eventIds.add(action.duplicate_client_event_id);
      }
      signedQrs.add(action.signed_qr);
      return Object.freeze({
        clientEventId: action.client_event_id.toLowerCase(),
        duplicateClientEventId: action.duplicate_client_event_id?.toLowerCase() ?? null,
        signedQr: action.signed_qr,
      });
    });
    return Object.freeze({
      accessToken: entry.access_token,
      actions: Object.freeze(actions),
      sessionId: entry.session_id.toLowerCase(),
      tripId: entry.trip_id.toLowerCase(),
    });
  });
}
