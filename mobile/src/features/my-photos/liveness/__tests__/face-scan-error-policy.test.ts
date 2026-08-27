import { ApiError } from '@/core/api/client';

import {
  faceScanFailureFromStableCode,
  shouldReplayLivenessCompletion,
  shouldReplayLivenessCompletionResult,
} from '../face-scan-error-policy';

describe('Face Scan server error policy', () => {
  it('normalizes prefixed and unprefixed no-face and multiple-face results', () => {
    expect(faceScanFailureFromStableCode('NO_FACE')).toBe('no_face');
    expect(faceScanFailureFromStableCode('MY_PHOTOS_NO_FACE')).toBe('no_face');
    expect(faceScanFailureFromStableCode('MULTIPLE_FACES')).toBe('multiple_faces');
    expect(faceScanFailureFromStableCode('MY_PHOTOS_MULTIPLE_FACES')).toBe('multiple_faces');
  });

  it.each([
    new TypeError('network lost'),
    new ApiError('provider unavailable', 503, 'MY_PHOTOS_PROVIDER_UNAVAILABLE', null),
    new ApiError('still processing', 409, 'MY_PHOTOS_SESSION_PROCESSING', 2),
  ])('retains and replays an ambiguous completion for %p', (error) => {
    expect(shouldReplayLivenessCompletion(error)).toBe(true);
  });

  it('does not replay a definitive liveness rejection', () => {
    expect(shouldReplayLivenessCompletion(
      new ApiError('rejected', 422, 'MY_PHOTOS_LIVENESS_REJECTED', null),
    )).toBe(false);
  });

  it('replays a retryable provider result but not a definitive provider result', () => {
    expect(shouldReplayLivenessCompletionResult('MY_PHOTOS_SESSION_PROCESSING', true)).toBe(true);
    expect(shouldReplayLivenessCompletionResult('PROVIDER_UNAVAILABLE', true)).toBe(true);
    expect(shouldReplayLivenessCompletionResult('PROVIDER_UNAVAILABLE', false)).toBe(false);
    expect(shouldReplayLivenessCompletionResult('LIVENESS_REJECTED', true)).toBe(false);
  });
});
