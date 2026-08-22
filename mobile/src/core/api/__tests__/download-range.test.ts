import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';

import {
  ApiError,
  authorizedDownloadToFile,
  registerAccessDeniedHandler,
} from '../client';
import { downloadNativeFileBounded } from '../native-file-download';

jest.mock('@/core/demo/demo-mode', () => ({ isDemoMode: () => false }));
jest.mock('../native-file-download', () => {
  const actual = jest.requireActual('../native-file-download');
  return { ...actual, downloadNativeFileBounded: jest.fn() };
});

const mockedNativeDownload = jest.mocked(downloadNativeFileBounded);

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
    mockedNativeDownload.mockReset();
  });

  afterEach(() => {
    useSessionStore.getState().clear();
    jest.restoreAllMocks();
  });

  it('rejects an invalid offset before making a network request', async () => {
    await expect(authorizedDownloadToFile(
      '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/documents/44444444-4444-4444-8444-444444444444/content?version=1',
      'a'.repeat(32),
      '/private/cache/download.tmp',
      4096,
      undefined,
      -1,
    )).rejects.toMatchObject<Partial<ApiError>>({ code: 'INVALID_DOWNLOAD_RANGE', status: 400 });
    expect(mockedNativeDownload).not.toHaveBeenCalled();
  });

  it('streams a resume request to an exact native path without forwarding redirects', async () => {
    mockedNativeDownload.mockResolvedValue({
      headers: {
        'content-length': '2048',
        'content-range': 'bytes 2048-4095/4096',
        'content-type': 'application/pdf',
      },
      redirects: [],
      status: 206,
    });

    await expect(authorizedDownloadToFile(
      '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/documents/44444444-4444-4444-8444-444444444444/content?version=1',
      'a'.repeat(32),
      '/private/cache/download.tmp',
      2048,
      undefined,
      2048,
    )).resolves.toMatchObject({ status: 206 });

    expect(mockedNativeDownload).toHaveBeenCalledWith(expect.objectContaining({
      destinationPath: '/private/cache/download.tmp',
      maximumBytes: 2048,
      headers: expect.objectContaining({
        Authorization: 'Bearer mobile-access-token',
        Range: 'bytes=2048-',
        'X-GC-Download-Token': 'a'.repeat(32),
      }),
    }));
  });

  it('maps a native 401 to an expired short-lived grant without purging trip access', async () => {
    const accessDenied = jest.fn(async () => undefined);
    const unregister = registerAccessDeniedHandler(accessDenied);
    mockedNativeDownload.mockResolvedValue({ headers: {}, redirects: [], status: 401 });

    try {
      await expect(authorizedDownloadToFile(
        '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/documents/44444444-4444-4444-8444-444444444444/content?version=1',
        'a'.repeat(32),
        '/private/cache/download.tmp',
        4096,
      )).rejects.toMatchObject<Partial<ApiError>>({
        code: 'DOWNLOAD_AUTH_EXPIRED',
        status: 401,
      });
      expect(accessDenied).not.toHaveBeenCalled();
    } finally {
      unregister();
    }
  });
});
