import type { DownloadQuality } from '../api/contracts';
import type { PhotoDownloadState } from './download-policy';

export type PhotoDownloadJob = Readonly<{
  id: string;
  batchId: string | null;
  namespace: string;
  tripId: string;
  passengerId: string;
  assetId: string;
  quality: DownloadQuality;
  wifiOnly: boolean;
  state: PhotoDownloadState;
  deliveryVersion: number;
  expectedSizeBytes: number | null;
  expectedChecksumSha256: string | null;
  contentType: 'image/jpeg' | 'image/png' | 'image/webp' | null;
  verifiedPlaintextBytes: number;
  encryptedSizeBytes: number | null;
  encryptedFileUri: string | null;
  attemptCount: number;
  preparationPollCount: number;
  integrityVerifiedAt: string | null;
  nextAttemptAt: string | null;
  stableErrorCode: string | null;
  authorizationExpiresAt: string | null;
  supportsRanges: boolean;
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
}>;

export type PhotoDownloadRow = Readonly<{
  id: string;
  batch_id: string | null;
  account_namespace: string;
  trip_id: string;
  passenger_id: string;
  media_asset_id: string;
  quality: DownloadQuality;
  wifi_only: number;
  state: PhotoDownloadState;
  delivery_version: number;
  expected_size_bytes: number | null;
  expected_checksum_sha256: string | null;
  content_type: PhotoDownloadJob['contentType'];
  verified_plaintext_bytes: number;
  encrypted_size_bytes: number | null;
  encrypted_file_uri: string | null;
  attempt_count: number;
  preparation_poll_count: number;
  integrity_verified_at: string | null;
  next_attempt_at: string | null;
  stable_error_code: string | null;
  authorization_expires_at: string | null;
  supports_ranges: number;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}>;

export type PhotoDownloadBatch = Readonly<{
  id: string;
  requestKind: 'filter_selection' | 'all_matched';
  checkpointFilter: 'best' | 'possible' | null;
  selectionFilter: 'best' | 'possible' | null;
  excludedAssetIds: readonly string[];
  cursor: string | null;
  enqueuedCount: number;
  enumeratedCount: number;
  expectedItemCount: number;
  quality: DownloadQuality;
  wifiOnly: boolean;
  galleryRevision: number;
  state: 'active' | 'paused' | 'completed' | 'cancelled' | 'failed';
}>;

export const PHOTO_DOWNLOAD_JOB_SELECT = `
  SELECT id, batch_id, account_namespace, trip_id, passenger_id, media_asset_id,
         quality, wifi_only, state, delivery_version, expected_size_bytes,
         expected_checksum_sha256, content_type, verified_plaintext_bytes,
         encrypted_size_bytes, encrypted_file_uri, attempt_count, preparation_poll_count,
         integrity_verified_at, next_attempt_at, stable_error_code,
         authorization_expires_at, supports_ranges, created_at, updated_at, completed_at
    FROM my_photos_downloads`;

export function mapPhotoDownloadRow(row: PhotoDownloadRow): PhotoDownloadJob {
  return {
    id: row.id,
    batchId: row.batch_id,
    namespace: row.account_namespace,
    tripId: row.trip_id,
    passengerId: row.passenger_id,
    assetId: row.media_asset_id,
    quality: row.quality,
    wifiOnly: Boolean(row.wifi_only),
    state: row.state,
    deliveryVersion: row.delivery_version,
    expectedSizeBytes: row.expected_size_bytes,
    expectedChecksumSha256: row.expected_checksum_sha256,
    contentType: row.content_type,
    verifiedPlaintextBytes: row.verified_plaintext_bytes,
    encryptedSizeBytes: row.encrypted_size_bytes,
    encryptedFileUri: row.encrypted_file_uri,
    attemptCount: row.attempt_count,
    preparationPollCount: row.preparation_poll_count,
    integrityVerifiedAt: row.integrity_verified_at,
    nextAttemptAt: row.next_attempt_at,
    stableErrorCode: row.stable_error_code,
    authorizationExpiresAt: row.authorization_expires_at,
    supportsRanges: Boolean(row.supports_ranges),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    completedAt: row.completed_at,
  };
}
