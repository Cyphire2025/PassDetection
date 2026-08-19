import { z } from 'zod';

import { ApiError, apiRequest } from '../client';

jest.mock('@/core/demo/demo-mode', () => ({ isDemoMode: () => false }));

const ResultSchema = z.object({ ok: z.literal(true) }).strict();

function jsonError(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

afterEach(() => {
  jest.restoreAllMocks();
});

test('preserves the bounded backend domain error code and message', async () => {
  jest.spyOn(globalThis, 'fetch').mockResolvedValue(jsonError(404, {
    error: { code: 'NOT_FOUND', message: 'Published mobile itinerary was not found' },
  }));

  await expect(apiRequest('/mobile/trips/example/itinerary', {
    authenticated: false,
    schema: ResultSchema,
  })).rejects.toMatchObject<Partial<ApiError>>({
    status: 404,
    code: 'NOT_FOUND',
    message: 'Published mobile itinerary was not found',
  });
});

test('keeps an unregistered FastAPI route distinguishable as HTTP_404', async () => {
  jest.spyOn(globalThis, 'fetch').mockResolvedValue(jsonError(404, { detail: 'Not Found' }));

  await expect(apiRequest('/mobile/missing-route', {
    authenticated: false,
    schema: ResultSchema,
  })).rejects.toMatchObject<Partial<ApiError>>({
    status: 404,
    code: 'HTTP_404',
    message: 'Not Found',
  });
});

test('rejects an error descriptor carrying undeclared debug metadata', async () => {
  jest.spyOn(globalThis, 'fetch').mockResolvedValue(jsonError(404, {
    error: {
      code: 'NOT_FOUND',
      message: 'Published mobile itinerary was not found',
      debug_context: 'must not cross the mobile boundary',
    },
  }));

  await expect(apiRequest('/mobile/trips/example/itinerary', {
    authenticated: false,
    schema: ResultSchema,
  })).rejects.toMatchObject<Partial<ApiError>>({
    status: 404,
    code: 'HTTP_404',
    message: 'The server could not complete this request.',
  });
});
