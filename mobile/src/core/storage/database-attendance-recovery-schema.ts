export const CURRENT_ATTENDANCE_RECOVERY_SCHEMA_SQL = `
  CREATE TABLE IF NOT EXISTS attendance_scan_issue_context (
    idempotency_key TEXT PRIMARY KEY NOT NULL
      REFERENCES pending_actions(idempotency_key) ON DELETE CASCADE,
    account_namespace TEXT NOT NULL,
    trip_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    session_label TEXT NOT NULL,
    passenger_id TEXT NOT NULL,
    passenger_label TEXT NOT NULL,
    scan_reference TEXT NOT NULL CHECK (
      length(scan_reference) = 64
      AND scan_reference NOT GLOB '*[^0-9a-f]*'
    ),
    captured_at TEXT NOT NULL,
    created_at TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_attendance_scan_issue_context_trip
    ON attendance_scan_issue_context(
      account_namespace, trip_id, session_id, created_at DESC
    );

  CREATE TABLE IF NOT EXISTS attendance_discard_tombstones (
    discard_event_id TEXT PRIMARY KEY NOT NULL,
    source_idempotency_key TEXT NOT NULL UNIQUE,
    account_namespace TEXT NOT NULL,
    trip_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    coordinator_user_id TEXT NOT NULL,
    installation_runtime_id TEXT NOT NULL,
    scan_reference TEXT NOT NULL CHECK (
      length(scan_reference) = 64
      AND scan_reference NOT GLOB '*[^0-9a-f]*'
    ),
    reason_category TEXT NOT NULL CHECK (reason_category IN (
      'operator_discard', 'wrong_group', 'expired_authorization',
      'activity_closed', 'duplicate', 'server_rejected',
      'corrupted_entry', 'other'
    )),
    captured_at TEXT,
    discarded_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
      'pending', 'sending', 'retryable', 'rejected', 'synchronized'
    )),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at TEXT,
    last_attempt_at TEXT,
    last_error_code TEXT,
    synchronized_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_attendance_discard_due
    ON attendance_discard_tombstones(
      account_namespace, state, next_attempt_at, discarded_at
    );
  CREATE INDEX IF NOT EXISTS idx_attendance_discard_session
    ON attendance_discard_tombstones(
      account_namespace, trip_id, session_id, state
    );
`;

export const ATTENDANCE_RECOVERY_MIGRATION_V25_SQL = `
  ALTER TABLE attendance_sessions ADD COLUMN scheduled_starts_at TEXT;
  ALTER TABLE attendance_sessions ADD COLUMN scheduled_ends_at TEXT;
  ALTER TABLE attendance_sessions ADD COLUMN schedule_timezone TEXT;
  ALTER TABLE attendance_sessions ADD COLUMN schedule_version INTEGER NOT NULL DEFAULT 1
    CHECK (schedule_version >= 1);
  CREATE INDEX IF NOT EXISTS idx_attendance_sessions_schedule
    ON attendance_sessions(
      account_namespace, trip_id, scheduled_starts_at, scheduled_ends_at
    );

  ${CURRENT_ATTENDANCE_RECOVERY_SCHEMA_SQL}
  PRAGMA user_version = 25;
`;
