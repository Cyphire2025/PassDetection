import type { MobileSession } from '@/core/auth/types';

import { requiredPreparationRunKey } from '../required-preload-policy';

const SESSION: MobileSession = {
  accessToken: 'access-token-one',
  accessTokenExpiresAt: '2026-08-02T21:00:00.000Z',
  refreshTokenExpiresAt: '2026-09-01T20:00:00.000Z',
  sessionId: '33333333-3333-4333-8333-333333333333',
  networkMode: 'online',
  principal: {
    id: '22222222-2222-4222-8222-222222222222',
    principalType: 'coordinator',
    agencyId: '11111111-1111-4111-8111-111111111111',
    displayName: 'Coordinator One',
    email: 'coordinator@example.com',
    phoneNumber: null,
    forcePasswordChange: false,
  },
};

test('profile and access-token refreshes do not restart required preparation', () => {
  const refreshed: MobileSession = {
    ...SESSION,
    accessToken: 'access-token-two',
    principal: {
      ...SESSION.principal,
      displayName: 'Coordinator Updated',
      phoneNumber: '+919876543210',
    },
  };

  expect(requiredPreparationRunKey(refreshed)).toBe(requiredPreparationRunKey(SESSION));
});

test('a different device session or account starts a distinct preparation run', () => {
  expect(requiredPreparationRunKey({ ...SESSION, sessionId: '44444444-4444-4444-8444-444444444444' }))
    .not.toBe(requiredPreparationRunKey(SESSION));
  expect(requiredPreparationRunKey({
    ...SESSION,
    principal: { ...SESSION.principal, id: '55555555-5555-4555-8555-555555555555' },
  })).not.toBe(requiredPreparationRunKey(SESSION));
  expect(requiredPreparationRunKey(null)).toBeNull();
});
