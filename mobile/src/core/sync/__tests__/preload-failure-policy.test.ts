import { ApiError } from '@/core/api/client';
import { OfflineDatabaseIntegrityError } from '@/core/storage/database';

import { canDeferWorkspacePreparationFailure } from '../preload-failure-policy';

test.each([
  new TypeError('Network request failed'),
  new TypeError('Failed to fetch'),
  new TypeError('Load failed'),
  new ApiError('Gateway unavailable', 503, 'DEPENDENCY_UNAVAILABLE', null),
  new ApiError('Slow down', 429, 'RATE_LIMITED', 5),
])('defers only a recognized transient transport failure: %s', (error) => {
  expect(canDeferWorkspacePreparationFailure(error)).toBe(true);
});

test.each([
  new TypeError("Cannot read properties of undefined (reading 'id')"),
  new ApiError('Forbidden', 403, 'AUTHORIZATION_ERROR', null),
  new ApiError('Not Found', 404, 'HTTP_404', null),
  new OfflineDatabaseIntegrityError(),
  new Error('Unexpected invariant failure'),
])('fails closed for authorization, integrity, or programmer failure: %s', (error) => {
  expect(canDeferWorkspacePreparationFailure(error)).toBe(false);
});
