import { z } from 'zod';

import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';

import { apiRequest } from '../client';

jest.mock('@/core/demo/demo-mode', () => ({ isDemoMode: () => false }));

const session = {
  accessToken: 'mobile-access-token',
  accessTokenExpiresAt: '2026-08-03T12:00:00.000Z',
  refreshTokenExpiresAt: '2026-09-03T12:00:00.000Z',
  sessionId: '33333333-3333-4333-8333-333333333333',
  networkMode: 'online',
  principal: {
    id: '22222222-2222-4222-8222-222222222222',
    accountId: '22222222-2222-4222-8222-222222222222',
    principalType: 'passenger',
    agencyId: '11111111-1111-4111-8111-111111111111',
    displayName: 'Passenger',
    email: null,
    phoneNumber: '+919876543210',
    forcePasswordChange: false,
  },
} satisfies MobileSession;

beforeEach(() => useSessionStore.getState().setSession(session));
afterEach(() => useSessionStore.getState().clear());

test.each([
  '/mobile/trips/../other-account',
  '/mobile/trips/%2e%2e/other-account',
  '/mobile/trips/tenant%2Fdocument',
  '/mobile/trips\\other-account',
  '//attacker.example/mobile/trips',
])('rejects non-canonical or traversal API path %s before fetch', async (path) => {
  const fetchSpy = jest.spyOn(globalThis, 'fetch');
  await expect(apiRequest(path, { schema: z.unknown() })).rejects.toThrow(/API paths/);
  expect(fetchSpy).not.toHaveBeenCalled();
  fetchSpy.mockRestore();
});
