import { ApiError } from '@/core/api/client';

import { userFacingErrorMessage } from '../user-facing-error';

describe('userFacingErrorMessage', () => {
  it('never exposes native or database diagnostics', () => {
    const internal = new Error(
      'Call to function NativeDatabase.execAsync has been rejected: cannot rollback - no transaction is active',
    );

    expect(userFacingErrorMessage(internal, 'Offline data could not be prepared.')).toBe(
      'Offline data could not be prepared.',
    );
  });

  it('maps transport, access, stale-state, and server failures to stable copy', () => {
    expect(userFacingErrorMessage(new TypeError('Network request failed'), 'fallback')).toBe(
      'Check your connection and try again.',
    );
    expect(userFacingErrorMessage(
      new ApiError('private provider detail', 403, 'FORBIDDEN', null),
      'fallback',
    )).toBe('You no longer have access to this information.');
    expect(userFacingErrorMessage(
      new ApiError('private provider detail', 409, 'DOCUMENT_VERSION_CHANGED', null),
      'fallback',
    )).toBe('This information changed. Refresh and try again.');
    expect(userFacingErrorMessage(
      new ApiError('private provider detail', 503, 'UNAVAILABLE', null),
      'fallback',
    )).toBe('The server could not complete this request. Try again.');
  });
});
