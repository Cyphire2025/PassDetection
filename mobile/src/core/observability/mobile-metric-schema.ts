export const MOBILE_METRIC_SCHEMA = Object.freeze({
  bootstrap_duration: {
    name: 'gc.mobile.bootstrap_to_interactive.duration',
    type: 'distribution',
    unit: 'millisecond',
    maximum: 120_000,
  },
  sync_duration: {
    name: 'gc.mobile.sync.duration',
    type: 'distribution',
    unit: 'millisecond',
    maximum: 600_000,
  },
  background_sync_duration: {
    name: 'gc.mobile.background_sync.duration',
    type: 'distribution',
    unit: 'millisecond',
    maximum: 300_000,
  },
  realtime_reconnect_delay: {
    name: 'gc.mobile.realtime.reconnect_delay',
    type: 'distribution',
    unit: 'millisecond',
    maximum: 120_000,
  },
  queue_depth: {
    name: 'gc.mobile.queue.depth',
    type: 'gauge',
    unit: 'item',
    maximum: 24_000,
  },
  sync_run: { name: 'gc.mobile.sync.run', type: 'counter', maximum: 1 },
  background_expiration: {
    name: 'gc.mobile.background.expiration',
    type: 'counter',
    maximum: 1,
  },
  realtime_reconnect: { name: 'gc.mobile.realtime.reconnect', type: 'counter', maximum: 1 },
  api_request_duration: {
    name: 'gc.mobile.api.request.duration',
    type: 'distribution',
    unit: 'millisecond',
    maximum: 120_000,
  },
  realtime_auth_rejection: {
    name: 'gc.mobile.realtime.auth_rejection',
    type: 'counter',
    maximum: 1,
  },
  push_registration: { name: 'gc.mobile.push.registration', type: 'counter', maximum: 1 },
  background_registration: {
    name: 'gc.mobile.background.registration',
    type: 'counter',
    maximum: 1,
  },
  document_prefetch: { name: 'gc.mobile.documents.prefetch', type: 'counter', maximum: 1 },
  attendance_discard: {
    name: 'gc.mobile.attendance.discarded',
    type: 'counter',
    maximum: 24_000,
  },
  attendance_needs_review_depth: { name: 'gc.mobile.attendance.needs_review.depth', type: 'gauge', unit: 'item', maximum: 1_000 },
  attendance_acknowledgement_latency: { name: 'gc.mobile.attendance.acknowledgement_latency', type: 'distribution', unit: 'millisecond', maximum: 120_000 },
  attendance_retry: { name: 'gc.mobile.attendance.retry', type: 'counter', maximum: 100 },
  attendance_refresh_recovery: { name: 'gc.mobile.attendance.refresh_recovery', type: 'counter', maximum: 100 },
  attendance_local_scan: { name: 'gc.mobile.attendance.scan.local_result', type: 'counter', maximum: 1 },
  attendance_confirmation: { name: 'gc.mobile.attendance.scan.confirmed', type: 'counter', maximum: 100 },
  attendance_oldest_pending_age: { name: 'gc.mobile.attendance.queue.oldest_pending_age', type: 'gauge', unit: 'millisecond', maximum: 2_592_000_000 },
  attendance_delivery_batch_size: { name: 'gc.mobile.attendance.delivery.batch_size', type: 'distribution', unit: 'item', maximum: 100 },
  attendance_delivery_failure: { name: 'gc.mobile.attendance.delivery.failure', type: 'counter', maximum: 1 },
  attendance_terminal_rejection: { name: 'gc.mobile.attendance.scan.terminal_rejection', type: 'counter', maximum: 100 },
  attendance_camera_to_local_queue: { name: 'gc.mobile.attendance.camera_to_local_queue', type: 'distribution', unit: 'millisecond', maximum: 120_000 },
  attendance_queue_to_confirmation: { name: 'gc.mobile.attendance.queue_to_confirmation', type: 'distribution', unit: 'millisecond', maximum: 2_592_000_000 },
  attendance_reconciliation: { name: 'gc.mobile.attendance.reconciliation', type: 'counter', maximum: 1 },
  authentication_lock: { name: 'gc.mobile.authentication.lock', type: 'counter', maximum: 1 },
  authentication_quarantine_depth: { name: 'gc.mobile.authentication.quarantine.depth', type: 'gauge', unit: 'item', maximum: 100 },
  realtime_connection: { name: 'gc.mobile.realtime.connection', type: 'counter', maximum: 1 },
  realtime_connection_duration: { name: 'gc.mobile.realtime.connection.duration', type: 'distribution', unit: 'millisecond', maximum: 120_000 },
  storage_maintenance_duration: { name: 'gc.mobile.storage.maintenance.duration', type: 'distribution', unit: 'millisecond', maximum: 120_000 },
  storage_maintenance_run: { name: 'gc.mobile.storage.maintenance.run', type: 'counter', maximum: 1 },
  storage_maintenance_changes: { name: 'gc.mobile.storage.maintenance.changed_rows', type: 'counter', maximum: 100_000 },
  my_photos_open: { name: 'gc.mobile.my_photos.open', type: 'counter', maximum: 1 },
  my_photos_enrollment_started: { name: 'gc.mobile.my_photos.enrollment.started', type: 'counter', maximum: 1 },
  my_photos_enrollment_completed: { name: 'gc.mobile.my_photos.enrollment.completed', type: 'counter', maximum: 1 },
  my_photos_enrollment_cancelled: { name: 'gc.mobile.my_photos.enrollment.cancelled', type: 'counter', maximum: 1 },
  my_photos_permission_denied: { name: 'gc.mobile.my_photos.permission_denied', type: 'counter', maximum: 1 },
  my_photos_provider_unavailable: { name: 'gc.mobile.my_photos.provider_unavailable', type: 'counter', maximum: 1 },
  my_photos_search_duration: { name: 'gc.mobile.my_photos.search.duration', type: 'distribution', unit: 'millisecond', maximum: 3_600_000 },
  my_photos_gallery_first_content: { name: 'gc.mobile.my_photos.gallery.first_content', type: 'distribution', unit: 'millisecond', maximum: 120_000 },
  my_photos_page_failure: { name: 'gc.mobile.my_photos.gallery.page_failure', type: 'counter', maximum: 1 },
  my_photos_thumbnail_failure: { name: 'gc.mobile.my_photos.gallery.thumbnail_failure', type: 'counter', maximum: 1 },
  my_photos_local_view_failure: { name: 'gc.mobile.my_photos.gallery.local_view_failure', type: 'counter', maximum: 1 },
  my_photos_grid_blank_incident: { name: 'gc.mobile.my_photos.gallery.blank_incident', type: 'counter', maximum: 1 },
  my_photos_download_event: { name: 'gc.mobile.my_photos.download.event', type: 'counter', maximum: 10_000 },
  my_photos_download_bytes: { name: 'gc.mobile.my_photos.download.bytes', type: 'distribution', unit: 'byte', maximum: 20 * 1024 * 1024 * 1024 },
  my_photos_resume_success: { name: 'gc.mobile.my_photos.download.resume_success', type: 'counter', maximum: 10_000 },
  my_photos_checksum_failure: { name: 'gc.mobile.my_photos.download.checksum_failure', type: 'counter', maximum: 10_000 },
  my_photos_low_storage_cancellation: { name: 'gc.mobile.my_photos.download.low_storage_cancellation', type: 'counter', maximum: 10_000 },
  my_photos_queue_recovery: { name: 'gc.mobile.my_photos.download.queue_recovery', type: 'counter', maximum: 10_000 },
} as const);

export const METRIC_ATTRIBUTE_VALUES = Object.freeze({
  outcome: new Set(['success', 'partial', 'failure', 'cancelled', 'timeout', 'offline']),
  api_operation: new Set([
    'authentication',
    'integrity',
    'push',
    'notifications',
    'trip_catalog',
    'attendance',
    'my_photos',
    'documents',
    'itinerary',
    'manager',
    'coordinator',
    'health',
    'other',
  ]),
  api_method: new Set(['get', 'post', 'put', 'patch', 'delete']),
  trigger: new Set(['startup', 'foreground', 'background', 'realtime', 'push', 'manual', 'mutation']),
  queue: new Set(['sync', 'attendance', 'documents']),
  attendance_result: new Set([
    'queued',
    'already_queued',
    'already_confirmed',
    'needs_review',
    'previously_rejected',
    'capacity_reached',
    'accepted',
    'already_applied',
  ]),
  terminal_reason: new Set([
    'authorization',
    'assignment',
    'activity_state',
    'timestamp',
    'idempotency',
    'qr_evidence',
    'local_payload',
    'local_expired',
    'client_request',
    'other',
  ]),
  reconciliation: new Set([
    'ready',
    'count_mismatch',
    'pending_queue',
    'needs_review',
    'unverifiable',
  ]),
  delivery_failure: new Set([
    'rate_limited',
    'server_error',
    'timeout',
    'network',
    'other',
  ]),
  my_photos_download_event: new Set([
    'started', 'completed', 'paused', 'resumed', 'failed', 'cancelled', 'recovered',
  ]),
} satisfies Record<string, ReadonlySet<string>>);

export type MobileMetricName = keyof typeof MOBILE_METRIC_SCHEMA;

export type MobileMetricAttributes = Readonly<{
  outcome?: 'success' | 'partial' | 'failure' | 'cancelled' | 'timeout' | 'offline';
  api_operation?:
    | 'authentication'
    | 'integrity'
    | 'push'
    | 'notifications'
    | 'trip_catalog'
    | 'attendance'
    | 'my_photos'
    | 'documents'
    | 'itinerary'
    | 'manager'
    | 'coordinator'
    | 'health'
    | 'other';
  api_method?: 'get' | 'post' | 'put' | 'patch' | 'delete';
  trigger?: 'startup' | 'foreground' | 'background' | 'realtime' | 'push' | 'manual' | 'mutation';
  queue?: 'sync' | 'attendance' | 'documents';
  attendance_result?:
    | 'queued'
    | 'already_queued'
    | 'already_confirmed'
    | 'needs_review'
    | 'previously_rejected'
    | 'capacity_reached'
    | 'accepted'
    | 'already_applied';
  terminal_reason?:
    | 'authorization'
    | 'assignment'
    | 'activity_state'
    | 'timestamp'
    | 'idempotency'
    | 'qr_evidence'
    | 'local_payload'
    | 'local_expired'
    | 'client_request'
    | 'other';
  reconciliation?:
    | 'ready'
    | 'count_mismatch'
    | 'pending_queue'
    | 'needs_review'
    | 'unverifiable';
  delivery_failure?: 'rate_limited' | 'server_error' | 'timeout' | 'network' | 'other';
  my_photos_download_event?:
    | 'started'
    | 'completed'
    | 'paused'
    | 'resumed'
    | 'failed'
    | 'cancelled'
    | 'recovered';
}>;
