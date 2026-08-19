import { ApiError } from '@/core/api/client';

import {
  documentRetryAction,
  documentRetryDelayMs,
  isDocumentMetadataConflict,
  isRetryableDocumentError,
  MAX_DOCUMENT_DOWNLOAD_ATTEMPTS,
} from '../document-retry-policy';

test('retries only bounded transient document failures', () => {
  expect(MAX_DOCUMENT_DOWNLOAD_ATTEMPTS).toBe(3);
  expect(isRetryableDocumentError(new ApiError('busy', 503, 'TEMPORARY', null))).toBe(true);
  expect(isRetryableDocumentError(new ApiError('slow down', 429, 'RATE_LIMITED', 2))).toBe(true);
  expect(isRetryableDocumentError(new ApiError('expired grant', 401, 'DOWNLOAD_AUTH_EXPIRED', null))).toBe(true);
  expect(isRetryableDocumentError(new ApiError('missing route', 404, 'HTTP_404', null))).toBe(true);
  expect(isRetryableDocumentError(new ApiError('gone route', 410, 'HTTP_410', null))).toBe(true);
  expect(isRetryableDocumentError(new ApiError('deleted', 404, 'NOT_FOUND', null))).toBe(false);
  expect(isRetryableDocumentError(new TypeError('Network request failed'))).toBe(true);
  expect(isRetryableDocumentError(new TypeError('Cannot read properties of undefined'))).toBe(false);
  expect(isRetryableDocumentError({ code: 'LOCAL_OFFLINE_CIPHERTEXT_CORRUPT' })).toBe(true);
  expect(isRetryableDocumentError(new Error('Downloaded document checksum did not match.'))).toBe(false);
  expect(isRetryableDocumentError(new ApiError('forbidden', 403, 'FORBIDDEN', null))).toBe(false);
});

test('requires metadata refresh rather than blind retry for version conflicts', () => {
  const conflict = new ApiError('changed', 409, 'DOCUMENT_VERSION_CHANGED', null);
  expect(isDocumentMetadataConflict(conflict)).toBe(true);
  expect(isRetryableDocumentError(conflict)).toBe(false);
  expect(documentRetryAction(conflict, 1, false)).toBe('refresh_metadata');
  expect(documentRetryAction(conflict, 2, true)).toBe('fail');
  expect(isDocumentMetadataConflict(new ApiError('forbidden', 403, 'FORBIDDEN', null))).toBe(false);
});

test('caps transient retries and fails closed for permanent errors', () => {
  expect(documentRetryAction(new ApiError('busy', 503, 'TEMPORARY', null), 1, false)).toBe('retry');
  expect(documentRetryAction(new ApiError('busy', 503, 'TEMPORARY', null), 3, false)).toBe('fail');
  expect(documentRetryAction({ code: 'LOCAL_OFFLINE_CIPHERTEXT_CORRUPT' }, 1, false)).toBe('retry');
  expect(documentRetryAction(new Error('checksum mismatch'), 1, false)).toBe('fail');
});

test('uses bounded exponential delay with jitter', () => {
  expect(documentRetryDelayMs(1, () => 0)).toBe(250);
  expect(documentRetryDelayMs(2, () => 0.5)).toBe(600);
  expect(documentRetryDelayMs(99, () => 1)).toBeLessThanOrEqual(1_200);
});
