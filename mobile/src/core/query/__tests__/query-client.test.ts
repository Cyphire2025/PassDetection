import { ApiError } from '@/core/api/client';

import { mobileQueryClient, queryRetryDelay, shouldRetryQuery } from '../query-client';

test('leaves reconnect refresh ownership to the manifest synchronization runtime', () => {
  expect(mobileQueryClient.getDefaultOptions().queries?.refetchOnReconnect).toBe(false);
});

test.each([
  [401, 'AUTHENTICATION_ERROR'],
  [403, 'AUTHORIZATION_ERROR'],
  [404, 'NOT_FOUND'],
  [409, 'CONFLICT'],
  [422, 'VALIDATION_ERROR'],
  [502, 'INVALID_RESPONSE'],
  [502, 'INVALID_CONTENT_TYPE'],
  [502, 'PAYLOAD_TOO_LARGE'],
] as const)('does not retry authoritative or contract errors (%s %s)', (status, code) => {
  expect(shouldRetryQuery(0, new ApiError('failed', status, code, null))).toBe(false);
});

test.each([408, 425, 429, 500, 502, 503])(
  'retries transient HTTP status %s within the bounded budget',
  (status) => {
    const error = new ApiError('temporary', status, 'TEMPORARY', null);
    expect(shouldRetryQuery(0, error)).toBe(true);
    expect(shouldRetryQuery(1, error)).toBe(true);
    expect(shouldRetryQuery(2, error)).toBe(false);
  },
);

test('retries native transport failures but not intentional cancellation', () => {
  expect(shouldRetryQuery(0, new TypeError('Network request failed'))).toBe(true);
  const aborted = new Error('cancelled');
  aborted.name = 'AbortError';
  expect(shouldRetryQuery(0, aborted)).toBe(false);
});

test('honors bounded server retry-after before exponential jitter', () => {
  expect(queryRetryDelay(0, new ApiError('busy', 429, 'RATE_LIMIT', 12))).toBe(12_000);
  expect(queryRetryDelay(0, new ApiError('busy', 429, 'RATE_LIMIT', 120))).toBe(60_000);

  jest.spyOn(Math, 'random').mockReturnValue(0.5);
  expect(queryRetryDelay(0, new Error('network'))).toBe(750);
  expect(queryRetryDelay(2, new Error('network'))).toBe(3_000);
  jest.restoreAllMocks();
});
