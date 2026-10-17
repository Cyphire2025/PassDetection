import { z } from 'zod';
import { apiRequest, authorizedDownloadToFile } from '../client';
import { demoOperationsRequest } from '@/core/demo/demo-operations';

jest.mock('@/core/demo/demo-mode', () => ({ isDemoMode: () => true }));
jest.mock('@/core/config/env', () => ({ env: { standaloneDemo: true } }));
jest.mock('@/core/demo/demo-operations', () => ({ demoOperationsRequest: jest.fn() }));

describe('standalone review network boundary', () => {
  const path = '/mobile/manager/groups/00000000-0000-4000-8000-000000000201/passengers';
  it('dispatches supported operations locally and still validates the result', async () => {
    const fetchSpy = jest.spyOn(globalThis, 'fetch');
    jest.mocked(demoOperationsRequest).mockResolvedValue({ total: 14 });
    expect(await apiRequest(path, { schema: z.object({ total: z.number() }) })).toEqual({ total: 14 });
    expect(demoOperationsRequest).toHaveBeenCalledWith(path, undefined, undefined);
    jest.mocked(demoOperationsRequest).mockResolvedValue({ total: 'invalid' });
    await expect(apiRequest(path, { schema: z.object({ total: z.number() }) })).rejects.toMatchObject({ code: 'DEMO_DATA_INVALID' });
    expect(fetchSpy).not.toHaveBeenCalled();
  });
  it('rejects unsupported endpoints and downloads before reaching a transport', async () => {
    const fetchSpy = jest.spyOn(globalThis, 'fetch');
    await expect(apiRequest('/mobile/trips', { schema: z.unknown() })).rejects.toMatchObject({ code: 'DEMO_LOCAL_ONLY' });
    await expect(authorizedDownloadToFile('/mobile/documents/demo/content', 'a'.repeat(32), '/private/demo.tmp', 4096)).rejects.toMatchObject({ code: 'DEMO_LOCAL_ONLY' });
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
