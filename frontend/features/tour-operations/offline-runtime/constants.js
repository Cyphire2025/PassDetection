export const SESSION_OWNER_KEY = "passdetection:session-owner";
export const DB_NAME = "passdetection-tour-ops";
export const DB_VERSION = 5;
export const PENDING_STORE_NAME = "pending-attendance-scans";
export const REJECTED_STORE_NAME = "rejected-attendance-scans";
export const OWNER_INDEX = "owner-user-id";
export const AUTHORIZATION_STORE_NAME = "coordinator-offline-authorizations";
export const SNAPSHOT_STORE_NAME = "coordinator-offline-snapshots";
export const DISCARD_STORE_NAME = "attendance-discard-tombstones";
export const CRYPTO_KEY_STORE_NAME = "offline-crypto-keys";
export const STORAGE_KEY_ID = "coordinator-offline-aes-gcm-v1";
export const MAX_PENDING_SCANS_PER_OWNER = 5000;
export const QR_PAYLOAD_PATTERN = /^pdatt:[A-Za-z0-9_-]{43}$/;
export const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const COORDINATOR_PATH_PATTERN = /^\/coordinator(?:\/|$)/;
export const SCANNER_PATH_PATTERN =
  /^\/coordinator\/groups\/([0-9a-f-]{36})(?:\/scanner)?(?:\/|$)/i;
