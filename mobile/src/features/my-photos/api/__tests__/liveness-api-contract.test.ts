import { apiRequest } from '@/core/api/client';

import {
  completeLivenessSession,
  MY_PHOTOS_LIVENESS_API_TIMEOUT_MS,
  startLivenessSession,
} from '../my-photos-api';

jest.mock('@/core/api/client', () => ({ apiRequest: jest.fn() }));

const GROUP_ID = '11111111-1111-4111-8111-111111111111';
const SESSION_ID = '22222222-2222-4222-8222-222222222222';
const START_REQUEST_ID = '33333333-3333-4333-8333-333333333333';
const COMPLETE_REQUEST_ID = '44444444-4444-4444-8444-444444444444';
const mockedApiRequest = jest.mocked(apiRequest);

beforeEach(() => {
  jest.clearAllMocks();
});

describe('My Photos liveness transport contract', () => {
  it('allows the bounded backend provider wait while preserving cancellation and idempotency', async () => {
    const startSignal = new AbortController().signal;
    const completeSignal = new AbortController().signal;
    mockedApiRequest.mockResolvedValueOnce({} as never).mockResolvedValueOnce({} as never);

    await startLivenessSession(
      GROUP_ID,
      'movement_and_light',
      startSignal,
      START_REQUEST_ID,
    );
    await completeLivenessSession(
      GROUP_ID,
      SESSION_ID,
      'expired',
      completeSignal,
      COMPLETE_REQUEST_ID,
    );

    expect(MY_PHOTOS_LIVENESS_API_TIMEOUT_MS).toBeGreaterThan(60_000);
    expect(MY_PHOTOS_LIVENESS_API_TIMEOUT_MS).toBe(75_000);
    expect(mockedApiRequest).toHaveBeenNthCalledWith(
      1,
      `/mobile/trips/${GROUP_ID}/my-photos/liveness-sessions`,
      expect.objectContaining({
        method: 'POST',
        body: {
          challenge_mode: 'movement_and_light',
          idempotency_key: START_REQUEST_ID,
        },
        timeoutMs: MY_PHOTOS_LIVENESS_API_TIMEOUT_MS,
        signal: startSignal,
      }),
    );
    expect(mockedApiRequest).toHaveBeenNthCalledWith(
      2,
      `/mobile/trips/${GROUP_ID}/my-photos/liveness-sessions/${SESSION_ID}/complete`,
      expect.objectContaining({
        method: 'POST',
        body: {
          outcome: 'expired',
          idempotency_key: COMPLETE_REQUEST_ID,
        },
        timeoutMs: MY_PHOTOS_LIVENESS_API_TIMEOUT_MS,
        signal: completeSignal,
      }),
    );
  });
});
