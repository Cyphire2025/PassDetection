import { ApiError } from '@/core/api/client';

const REVOKED_CODES = new Set([
  'MY_PHOTOS_ACCESS_EXPIRED',
  'MY_PHOTOS_ACCESS_REVOKED',
  'MOBILE_TRIP_ACCESS_EXPIRED',
  'MOBILE_TRIP_ACCESS_REVOKED',
]);

export function isMyPhotosAccessRevokedError(error: unknown): boolean {
  return error instanceof ApiError
    && (
      error.status === 401
      || error.status === 403
      || error.status === 410
      || REVOKED_CODES.has(error.code)
    );
}
