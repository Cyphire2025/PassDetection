import { mobileQueryClient } from '@/core/query/query-client';
import { cancelRequiredPreparation } from '@/core/sync/required-preparation-lease';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import { bootstrapApplicationSession } from '../application-bootstrap';
import { bootstrapSession } from '../session-service';
import { useSessionStore } from '../session-store';
import type { MobileSession } from '../types';

jest.mock('../session-service', () => ({ bootstrapSession: jest.fn() }));

const mockedBootstrapSession = jest.mocked(bootstrapSession);

const existingSession: MobileSession = {
  accessToken: 'existing-access-token',
  accessTokenExpiresAt: '2030-01-01T01:00:00.000Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
  sessionId: 'existing-session',
  networkMode: 'online',
  principal: {
    id: 'principal-a',
    accountId: 'account-a',
    principalType: 'passenger',
    agencyId: 'agency-a',
    displayName: 'Existing Passenger',
    email: null,
    phoneNumber: null,
    forcePasswordChange: false,
  },
};

beforeEach(() => {
  mockedBootstrapSession.mockReset();
  useSessionStore.getState().clear();
  useSelectedTripStore.getState().clear();
  mobileQueryClient.clear();
  cancelRequiredPreparation();
});

test.each([
  ['SecureStore', new Error('SecureStore native read rejected')],
  ['SQLite', new Error('NativeDatabase.execAsync rejected')],
])('%s bootstrap rejection becomes recoverable anonymous state', async (_source, failure) => {
  useSessionStore.getState().setSession(existingSession);
  useSelectedTripStore.getState().selectTrip('trip-a');
  mobileQueryClient.setQueryData(['private', 'account-a'], { passenger: 'private' });
  mockedBootstrapSession.mockRejectedValueOnce(failure);

  await expect(bootstrapApplicationSession()).resolves.toEqual({
    ok: false,
    errorCode: 'SESSION_BOOTSTRAP_FAILED',
  });

  expect(useSessionStore.getState()).toMatchObject({
    status: 'anonymous',
    session: null,
    bootstrapErrorCode: 'SESSION_BOOTSTRAP_FAILED',
  });
  expect(useSelectedTripStore.getState().tripId).toBeNull();
  expect(mobileQueryClient.getQueryData(['private', 'account-a'])).toBeUndefined();
});

test('a retry can restore a session after a native bootstrap rejection', async () => {
  mockedBootstrapSession
    .mockRejectedValueOnce(new Error('SecureStore native read rejected'))
    .mockImplementationOnce(async () => {
      useSessionStore.getState().setSession(existingSession);
    });

  await expect(bootstrapApplicationSession()).resolves.toMatchObject({ ok: false });
  await expect(bootstrapApplicationSession()).resolves.toEqual({ ok: true });
  expect(useSessionStore.getState()).toMatchObject({
    status: 'authenticated',
    session: existingSession,
    bootstrapErrorCode: null,
  });
  expect(mockedBootstrapSession).toHaveBeenLastCalledWith({ validation: 'background' });
});
