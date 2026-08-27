/**
 * Account-local My Photos metadata and queue state.
 * Media bytes never enter SQLite.
 */
export const MY_PHOTOS_STORAGE_SCHEMA_SQL = `
  CREATE TABLE IF NOT EXISTS my_photos_summary_cache (
    account_namespace TEXT NOT NULL,
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    passenger_id TEXT NOT NULL CHECK (length(passenger_id) BETWEEN 1 AND 128),
    gallery_revision INTEGER NOT NULL CHECK (gallery_revision >= 0),
    response_json TEXT NOT NULL CHECK (length(response_json) BETWEEN 2 AND 65536),
    cached_at TEXT NOT NULL,
    PRIMARY KEY(account_namespace, trip_id, passenger_id)
  );
  CREATE INDEX IF NOT EXISTS idx_my_photos_summary_revision
    ON my_photos_summary_cache(account_namespace, trip_id, passenger_id, gallery_revision);

  CREATE TABLE IF NOT EXISTS my_photos_page_cache (
    account_namespace TEXT NOT NULL,
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    passenger_id TEXT NOT NULL CHECK (length(passenger_id) BETWEEN 1 AND 128),
    gallery_revision INTEGER NOT NULL CHECK (gallery_revision >= 0),
    match_filter TEXT NOT NULL CHECK (match_filter IN ('best', 'possible', 'all')),
    page_ordinal INTEGER NOT NULL CHECK (page_ordinal >= 0),
    item_ordinal INTEGER NOT NULL CHECK (item_ordinal >= 0),
    media_asset_id TEXT NOT NULL CHECK (length(media_asset_id) BETWEEN 1 AND 128),
    response_json TEXT NOT NULL CHECK (length(response_json) BETWEEN 2 AND 32768),
    cached_at TEXT NOT NULL,
    PRIMARY KEY(
      account_namespace, trip_id, passenger_id, gallery_revision,
      match_filter, page_ordinal, item_ordinal
    ),
    UNIQUE(
      account_namespace, trip_id, passenger_id, gallery_revision,
      match_filter, media_asset_id
    )
  );
  CREATE INDEX IF NOT EXISTS idx_my_photos_page_window
    ON my_photos_page_cache(
      account_namespace, trip_id, passenger_id, gallery_revision,
      match_filter, page_ordinal, item_ordinal
    );

  CREATE TABLE IF NOT EXISTS my_photos_cursor_cache (
    account_namespace TEXT NOT NULL,
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    passenger_id TEXT NOT NULL CHECK (length(passenger_id) BETWEEN 1 AND 128),
    gallery_revision INTEGER NOT NULL CHECK (gallery_revision >= 0),
    match_filter TEXT NOT NULL CHECK (match_filter IN ('best', 'possible', 'all')),
    page_ordinal INTEGER NOT NULL CHECK (page_ordinal BETWEEN 0 AND 255),
    request_cursor TEXT CHECK (request_cursor IS NULL OR length(request_cursor) BETWEEN 16 AND 768),
    next_cursor TEXT CHECK (next_cursor IS NULL OR length(next_cursor) BETWEEN 16 AND 768),
    cached_at TEXT NOT NULL,
    PRIMARY KEY(
      account_namespace, trip_id, passenger_id, gallery_revision,
      match_filter, page_ordinal
    )
  );
  CREATE UNIQUE INDEX IF NOT EXISTS idx_my_photos_cursor_identity
    ON my_photos_cursor_cache(
      account_namespace, trip_id, passenger_id, gallery_revision,
      match_filter, request_cursor
    ) WHERE request_cursor IS NOT NULL;

  CREATE TABLE IF NOT EXISTS my_photos_download_batches (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
    account_namespace TEXT NOT NULL,
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    passenger_id TEXT NOT NULL CHECK (length(passenger_id) BETWEEN 1 AND 128),
    request_kind TEXT NOT NULL CHECK (request_kind IN ('one', 'selected', 'filter_selection', 'all_matched')),
    quality TEXT NOT NULL CHECK (quality IN ('original', 'optimized')),
    state TEXT NOT NULL CHECK (state IN ('active', 'paused', 'completed', 'cancelled', 'failed')),
    wifi_only INTEGER NOT NULL DEFAULT 0 CHECK (wifi_only IN (0, 1)),
    estimated_bytes INTEGER CHECK (estimated_bytes IS NULL OR estimated_bytes >= 0),
    checkpoint_filter TEXT CHECK (checkpoint_filter IS NULL OR checkpoint_filter IN ('best', 'possible')),
    enqueued_count INTEGER NOT NULL DEFAULT 0 CHECK (enqueued_count >= 0),
    enumerated_count INTEGER NOT NULL DEFAULT 0 CHECK (enumerated_count >= 0),
    expected_item_count INTEGER CHECK (expected_item_count IS NULL OR expected_item_count >= 0),
    selection_filter TEXT CHECK (selection_filter IS NULL OR selection_filter IN ('best', 'possible')),
    excluded_asset_ids_json TEXT NOT NULL DEFAULT '[]' CHECK (length(excluded_asset_ids_json) <= 65536),
    cursor TEXT CHECK (cursor IS NULL OR length(cursor) BETWEEN 16 AND 768),
    gallery_revision INTEGER NOT NULL CHECK (gallery_revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, account_namespace, trip_id, passenger_id)
  );
  CREATE INDEX IF NOT EXISTS idx_my_photos_batch_owner
    ON my_photos_download_batches(account_namespace, trip_id, passenger_id, state, updated_at);
  CREATE UNIQUE INDEX IF NOT EXISTS idx_my_photos_single_active_download_all
    ON my_photos_download_batches(
      account_namespace, trip_id, passenger_id, quality, gallery_revision
    )
    WHERE request_kind = 'all_matched' AND state IN ('active', 'paused');
  CREATE UNIQUE INDEX IF NOT EXISTS idx_my_photos_single_active_filter_download
    ON my_photos_download_batches(
      account_namespace, trip_id, passenger_id, quality, selection_filter,
      excluded_asset_ids_json, gallery_revision
    )
    WHERE request_kind = 'filter_selection' AND state IN ('active', 'paused');

  CREATE TABLE IF NOT EXISTS my_photos_downloads (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
    batch_id TEXT,
    account_namespace TEXT NOT NULL,
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    passenger_id TEXT NOT NULL CHECK (length(passenger_id) BETWEEN 1 AND 128),
    media_asset_id TEXT NOT NULL CHECK (length(media_asset_id) BETWEEN 1 AND 128),
    quality TEXT NOT NULL CHECK (quality IN ('original', 'optimized')),
    wifi_only INTEGER NOT NULL DEFAULT 0 CHECK (wifi_only IN (0, 1)),
    state TEXT NOT NULL CHECK (state IN (
      'queued', 'waiting_wifi', 'waiting_media_preparation', 'downloading',
      'paused', 'retrying', 'completed', 'cancelled', 'failed', 'corrupt',
      'expired_authorization', 'removed'
    )),
    delivery_version INTEGER NOT NULL CHECK (delivery_version >= 0),
    expected_size_bytes INTEGER CHECK (expected_size_bytes IS NULL OR expected_size_bytes >= 0),
    expected_checksum_sha256 TEXT CHECK (
      expected_checksum_sha256 IS NULL OR (
        length(expected_checksum_sha256) = 64
        AND expected_checksum_sha256 NOT GLOB '*[^0-9a-f]*'
      )
    ),
    content_type TEXT CHECK (content_type IS NULL OR content_type IN (
      'image/jpeg', 'image/png', 'image/webp'
    )),
    verified_plaintext_bytes INTEGER NOT NULL DEFAULT 0 CHECK (verified_plaintext_bytes >= 0),
    encrypted_size_bytes INTEGER CHECK (encrypted_size_bytes IS NULL OR encrypted_size_bytes >= 29),
    encrypted_file_uri TEXT CHECK (encrypted_file_uri IS NULL OR length(encrypted_file_uri) BETWEEN 1 AND 2048),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 20),
    preparation_poll_count INTEGER NOT NULL DEFAULT 0 CHECK (preparation_poll_count >= 0),
    integrity_verified_at TEXT,
    next_attempt_at TEXT,
    stable_error_code TEXT CHECK (stable_error_code IS NULL OR length(stable_error_code) BETWEEN 1 AND 64),
    authorization_expires_at TEXT,
    supports_ranges INTEGER NOT NULL DEFAULT 0 CHECK (supports_ranges IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    CHECK (
      state != 'completed' OR (
        encrypted_file_uri IS NOT NULL
        AND expected_size_bytes IS NOT NULL
        AND expected_checksum_sha256 IS NOT NULL
        AND delivery_version >= 1
        AND verified_plaintext_bytes = expected_size_bytes
        AND encrypted_size_bytes IS NOT NULL
        AND completed_at IS NOT NULL
      )
    ),
    FOREIGN KEY(batch_id, account_namespace, trip_id, passenger_id)
      REFERENCES my_photos_download_batches(id, account_namespace, trip_id, passenger_id)
      ON DELETE RESTRICT
  );
  CREATE UNIQUE INDEX IF NOT EXISTS idx_my_photos_download_asset
    ON my_photos_downloads(account_namespace, trip_id, passenger_id, media_asset_id, quality)
    WHERE state != 'removed';
  CREATE INDEX IF NOT EXISTS idx_my_photos_download_queue
    ON my_photos_downloads(account_namespace, state, next_attempt_at, created_at);
  CREATE INDEX IF NOT EXISTS idx_my_photos_download_owner
    ON my_photos_downloads(account_namespace, trip_id, passenger_id, state, updated_at);
  CREATE INDEX IF NOT EXISTS idx_my_photos_completed_download_page
    ON my_photos_downloads(
      account_namespace, trip_id, passenger_id, completed_at DESC, id DESC
    )
    WHERE state = 'completed';

  CREATE TABLE IF NOT EXISTS my_photos_reconciliation_state (
    account_namespace TEXT NOT NULL,
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    passenger_id TEXT NOT NULL CHECK (length(passenger_id) BETWEEN 1 AND 128),
    cursor_created_at TEXT,
    cursor_id TEXT,
    cycle_started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(account_namespace, trip_id, passenger_id),
    CHECK ((cursor_created_at IS NULL) = (cursor_id IS NULL))
  );
`;
