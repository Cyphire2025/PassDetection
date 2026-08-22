export const CURRENT_PENDING_ACTIONS_SCHEMA_SQL = `
  CREATE TABLE IF NOT EXISTS pending_actions (
    idempotency_key TEXT PRIMARY KEY NOT NULL,
    account_namespace TEXT NOT NULL,
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    dedupe_key TEXT,
    payload_json TEXT NOT NULL,
    base_version INTEGER,
    state TEXT NOT NULL CHECK (state IN (
      'pending', 'sending', 'retryable', 'needs_review', 'rejected'
    )),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    refresh_attempt_count INTEGER NOT NULL DEFAULT 0
      CHECK (refresh_attempt_count BETWEEN 0 AND 1),
    next_attempt_at TEXT,
    last_error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_pending_drain
    ON pending_actions(account_namespace, trip_id, state, next_attempt_at, created_at);
  CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_action_dedupe
    ON pending_actions(account_namespace, trip_id, action_type, dedupe_key)
    WHERE dedupe_key IS NOT NULL;
  CREATE INDEX IF NOT EXISTS idx_pending_attendance_session
    ON pending_actions(
      account_namespace,
      trip_id,
      state,
      (CASE WHEN json_valid(payload_json)
        THEN json_extract(payload_json, '$.session_id') ELSE NULL END)
    )
    WHERE action_type = 'attendance.scan';
  CREATE TRIGGER IF NOT EXISTS minimize_rejected_attendance_insert
    AFTER INSERT ON pending_actions
    WHEN NEW.action_type = 'attendance.scan'
      AND NEW.state = 'rejected'
      AND NEW.payload_json <> '{}'
  BEGIN
    UPDATE pending_actions
       SET payload_json = '{}'
     WHERE idempotency_key = NEW.idempotency_key;
  END;
  CREATE TRIGGER IF NOT EXISTS minimize_rejected_attendance_update
    AFTER UPDATE OF state, payload_json ON pending_actions
    WHEN NEW.action_type = 'attendance.scan'
      AND NEW.state = 'rejected'
      AND NEW.payload_json <> '{}'
  BEGIN
    UPDATE pending_actions
       SET payload_json = '{}'
     WHERE idempotency_key = NEW.idempotency_key;
  END;
`;

export const ATTENDANCE_NEEDS_REVIEW_MIGRATION_SQL = `
  ALTER TABLE pending_actions RENAME TO pending_actions_v22;
  CREATE TABLE pending_actions (
    idempotency_key TEXT PRIMARY KEY NOT NULL,
    account_namespace TEXT NOT NULL,
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    dedupe_key TEXT,
    payload_json TEXT NOT NULL,
    base_version INTEGER,
    state TEXT NOT NULL CHECK (state IN (
      'pending', 'sending', 'retryable', 'needs_review', 'rejected'
    )),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    refresh_attempt_count INTEGER NOT NULL DEFAULT 0
      CHECK (refresh_attempt_count BETWEEN 0 AND 1),
    next_attempt_at TEXT,
    last_error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  );
  INSERT INTO pending_actions(
    idempotency_key, account_namespace, trip_id, action_type, dedupe_key,
    payload_json, base_version, state, attempt_count, refresh_attempt_count,
    next_attempt_at, last_error_code, created_at, updated_at
  )
  SELECT idempotency_key, account_namespace, trip_id, action_type, dedupe_key,
         payload_json, base_version, state, attempt_count, 0,
         next_attempt_at, last_error_code, created_at, updated_at
    FROM pending_actions_v22;
  DROP TABLE pending_actions_v22;
  CREATE INDEX idx_pending_drain
    ON pending_actions(account_namespace, trip_id, state, next_attempt_at, created_at);
  CREATE UNIQUE INDEX idx_pending_action_dedupe
    ON pending_actions(account_namespace, trip_id, action_type, dedupe_key)
    WHERE dedupe_key IS NOT NULL;
  CREATE INDEX idx_pending_attendance_session
    ON pending_actions(
      account_namespace,
      trip_id,
      state,
      (CASE WHEN json_valid(payload_json)
        THEN json_extract(payload_json, '$.session_id') ELSE NULL END)
    )
    WHERE action_type = 'attendance.scan';
  PRAGMA user_version = 23;
`;

export const REJECTED_ATTENDANCE_MINIMIZATION_MIGRATION_SQL = `
  UPDATE pending_actions
     SET payload_json = '{}'
   WHERE action_type = 'attendance.scan'
     AND state = 'rejected';
  CREATE TRIGGER IF NOT EXISTS minimize_rejected_attendance_insert
    AFTER INSERT ON pending_actions
    WHEN NEW.action_type = 'attendance.scan'
      AND NEW.state = 'rejected'
      AND NEW.payload_json <> '{}'
  BEGIN
    UPDATE pending_actions
       SET payload_json = '{}'
     WHERE idempotency_key = NEW.idempotency_key;
  END;
  CREATE TRIGGER IF NOT EXISTS minimize_rejected_attendance_update
    AFTER UPDATE OF state, payload_json ON pending_actions
    WHEN NEW.action_type = 'attendance.scan'
      AND NEW.state = 'rejected'
      AND NEW.payload_json <> '{}'
  BEGIN
    UPDATE pending_actions
       SET payload_json = '{}'
     WHERE idempotency_key = NEW.idempotency_key;
  END;
  PRAGMA user_version = 24;
`;
