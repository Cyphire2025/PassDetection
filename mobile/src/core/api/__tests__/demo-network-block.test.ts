import { z } from 'zod';

import { ApiError, apiRequest, authorizedDownloadToFile } from '../client';

jest.mock('@/core/demo/demo-mode', () => ({ isDemoMode: () => true }));

describe('demo network boundary', () => {
  it('blocks JSON API calls before fetch', async () => {
    const fetchSpy = jest.spyOn(globalThis, 'fetch');

    await expect(apiRequest('/mobile/trips', { schema: z.unknown() })).rejects.toMatchObject<
      Partial<ApiError>
    >({ code: 'DEMO_LOCAL_ONLY', status: 503 });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('blocks document downloads before fetch', async () => {
    const fetchSpy = jest.spyOn(globalThis, 'fetch');

    await expect(
      authorizedDownloadToFile(
        '/mobile/documents/demo/content',
        'a'.repeat(32),
        '/private/cache/download.tmp',
        4096,
      ),
    ).rejects.toMatchObject<Partial<ApiError>>({ code: 'DEMO_LOCAL_ONLY', status: 503 });
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
