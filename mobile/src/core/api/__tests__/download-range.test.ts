import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';

import { ApiError, authorizedDownloadResponse, registerAccessDeniedHandler } from '../client';

jest.mock('@/core/demo/demo-mode', () => ({ isDemoMode: () => false }));

const session: MobileSession = {
  accessToken: 'mobile-access-token',
  accessTokenExpiresAt: new Date(Date.now() + 60_000).toISOString(),
  refreshTokenExpiresAt: new Date(Date.now() + 120_000).toISOString(),
  sessionId: 'session-id',
  networkMode: 'online',
  principal: {
    id: '11111111-1111-4111-8111-111111111111',
    accountId: '11111111-1111-4111-8111-111111111111',
    principalType: 'passenger',
    agencyId: '22222222-2222-4222-8222-222222222222',
    displayName: 'Passenger',
    email: null,
    phoneNumber: '+919999999999',
    forcePasswordChange: false,
  },
};

describe('authorized document resume requests', () => {
  beforeEach(() => {
    useSessionStore.getState().setSession(session);
  });

  afterEach(() => {
    useSessionStore.getState().clear();
    jest.restoreAllMocks();
  });

  it('sends a single open-ended byte range with the signed grant', async () => {
    const response = {
      ok: true,
      status: 206,
      headers: new Headers(),
    } as Response;
    const fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(response);

    await expect(authorizedDownloadResponse(
      '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/documents/44444444-4444-4444-8444-444444444444/content?version=1',
      'a'.repeat(32),
      undefined,
      2048,
    )).resolves.toBe(response);

    const request = fetchSpy.mock.calls[0]?.[1];
    expect(request?.headers).toMatchObject({
      Range: 'bytes=2048-',
      'X-GC-Download-Token': 'a'.repeat(32),
    });
  });

  it('rejects an invalid offset before making a network request', async () => {
    const fetchSpy = jest.spyOn(globalThis, 'fetch');

    await expect(authorizedDownloadResponse(
      '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/documents/44444444-4444-4444-8444-444444444444/content?version=1',
      'a'.repeat(32),
      undefined,
      -1,
    )).rejects.toMatchObject<Partial<ApiError>>({ code: 'INVALID_DOWNLOAD_RANGE', status: 400 });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('refreshes an expired download grant without purging valid trip access', async () => {
    const accessDenied = jest.fn(async () => undefined);
    const unregister = registerAccessDeniedHandler(accessDenied);
    jest.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: false,
      status: 401,
      headers: new Headers(),
    } as Response);

    try {
      await expect(authorizedDownloadResponse(
        '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/documents/44444444-4444-4444-8444-444444444444/content?version=1',
        'a'.repeat(32),
      )).rejects.toMatchObject<Partial<ApiError>>({ code: 'DOWNLOAD_AUTH_EXPIRED', status: 401 });
      expect(accessDenied).not.toHaveBeenCalled();
    } finally {
      unregister();
    }
  });
});
