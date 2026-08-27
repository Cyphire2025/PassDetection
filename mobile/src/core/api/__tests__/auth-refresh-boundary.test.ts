import { z } from 'zod';

import type { MobileSession } from '@/core/auth/types';
import {
  invalidateAuthenticationBoundary,
  useSessionStore,
} from '@/core/auth/session-store';

import { ApiError, apiRequest, registerRefreshHandler } from '../client';

jest.mock('@/core/demo/demo-mode', () => ({ isDemoMode: () => false }));

const sessionA: MobileSession = {
  accessToken: 'access-a-'.padEnd(48, 'a'),
  accessTokenExpiresAt: '2026-08-03T12:00:00.000Z',
  refreshTokenExpiresAt: '2026-09-03T12:00:00.000Z',
  sessionId: '33333333-3333-4333-8333-333333333333',
  networkMode: 'online',
  principal: {
    id: '22222222-2222-4222-8222-222222222222',
    accountId: '22222222-2222-4222-8222-222222222222',
    principalType: 'passenger',
    agencyId: '11111111-1111-4111-8111-111111111111',
    displayName: 'Passenger A',
    email: null,
    phoneNumber: '+919876543210',
    forcePasswordChange: false,
  },
};

const sessionB: MobileSession = {
  accessToken: 'access-b-'.padEnd(48, 'b'),
  accessTokenExpiresAt: '2026-08-03T12:00:00.000Z',
  refreshTokenExpiresAt: '2026-09-03T12:00:00.000Z',
  sessionId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  networkMode: 'online',
  principal: {
    id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    accountId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    principalType: 'passenger',
    agencyId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    displayName: 'Passenger B',
    email: null,
    phoneNumber: '+919876543211',
    forcePasswordChange: false,
  },
};

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function jsonResponse(status: number, value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const ResultSchema = z.object({ value: z.string() }).strict();
let restoreFetch: typeof globalThis.fetch;

beforeEach(() => {
  invalidateAuthenticationBoundary();
  useSessionStore.getState().setSession(sessionA);
  restoreFetch = globalThis.fetch;
});

afterEach(() => {
  globalThis.fetch = restoreFetch;
  useSessionStore.getState().clear();
});

test('an account switch invalidates a pending refresh and prevents cross-account retry', async () => {
  const refreshStarted = deferred<void>();
  const refreshResponse = deferred<string | null>();
  const refreshHandler = jest.fn(async () => {
    refreshStarted.resolve();
    return refreshResponse.promise;
  });
  const unregister = registerRefreshHandler(refreshHandler);
  const fetchMock = jest.fn(async () =>
    jsonResponse(401, { detail: 'Expired access token' }));
  globalThis.fetch = fetchMock as typeof globalThis.fetch;

  const request = apiRequest('/mobile/trips', { schema: ResultSchema });
  await refreshStarted.promise;
  invalidateAuthenticationBoundary();
  useSessionStore.getState().setSession(sessionB);
  refreshResponse.resolve('stale-access-a-'.padEnd(48, 'a'));

  await expect(request).rejects.toMatchObject<Partial<ApiError>>({
    status: 409,
    code: 'AUTH_CONTEXT_CHANGED',
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(refreshHandler).toHaveBeenCalledTimes(1);
  expect(useSessionStore.getState().session?.principal.id).toBe(sessionB.principal.id);
  unregister();
});

test('concurrent 401 responses in one session share one refresh operation', async () => {
  const refreshStarted = deferred<void>();
  const allowRefresh = deferred<void>();
  const rotatedSession: MobileSession = {
    ...sessionA,
    accessToken: 'rotated-access-a-'.padEnd(48, 'r'),
  };
  const refreshHandler = jest.fn(async () => {
    refreshStarted.resolve();
    await allowRefresh.promise;
    useSessionStore.getState().setSession(rotatedSession);
    return rotatedSession.accessToken;
  });
  const unregister = registerRefreshHandler(refreshHandler);
  let calls = 0;
  const fetchMock = jest.fn(async () => {
    calls += 1;
    return calls <= 2
      ? jsonResponse(401, { detail: 'Expired access token' })
      : jsonResponse(200, { value: 'ready' });
  });
  globalThis.fetch = fetchMock as typeof globalThis.fetch;

  const first = apiRequest('/mobile/trips', { schema: ResultSchema });
  const second = apiRequest('/mobile/me', { schema: ResultSchema });
  await refreshStarted.promise;
  allowRefresh.resolve();

  await expect(Promise.all([first, second])).resolves.toEqual([
    { value: 'ready' },
    { value: 'ready' },
  ]);
  expect(refreshHandler).toHaveBeenCalledTimes(1);
  expect(fetchMock).toHaveBeenCalledTimes(4);
  unregister();
});

test('an account switch while the response body is still being read cannot publish stale data', async () => {
  const bodyReadStarted = deferred<void>();
  const body = deferred<ArrayBuffer>();
  globalThis.fetch = jest.fn(async () => ({
    status: 200,
    ok: true,
    headers: {
      get: (name: string) => name.toLowerCase() === 'content-type'
        ? 'application/json'
        : null,
    },
    arrayBuffer: jest.fn(() => {
      bodyReadStarted.resolve();
      return body.promise;
    }),
  } as unknown as Response)) as typeof globalThis.fetch;

  const request = apiRequest('/mobile/trips', { schema: ResultSchema });
  await bodyReadStarted.promise;
  invalidateAuthenticationBoundary();
  useSessionStore.getState().setSession(sessionB);
  body.resolve(new TextEncoder().encode(JSON.stringify({ value: 'stale-account-a' })).buffer as ArrayBuffer);

  await expect(request).rejects.toMatchObject<Partial<ApiError>>({
    status: 409,
    code: 'AUTH_CONTEXT_CHANGED',
  });
});
