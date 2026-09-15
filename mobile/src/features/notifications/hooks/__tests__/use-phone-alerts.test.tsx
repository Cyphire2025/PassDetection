import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react-native';
import type { PropsWithChildren } from 'react';

import { apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';

import { usePhoneAlerts } from '../use-phone-alerts';

jest.mock('@/core/api/client', () => ({ apiRequest: jest.fn() }));
const session: MobileSession = {
  accessToken: 'test-token', accessTokenExpiresAt: '2030-01-01T00:00:00Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00Z', sessionId: 'session-a', networkMode: 'online',
  principal: { id: 'user-a', accountId: 'account-a', agencyId: 'agency-a', principalType: 'passenger',
    displayName: 'Test', email: null, phoneNumber: null, forcePasswordChange: false },
};
const alert = { id: '11111111-1111-4111-8111-111111111111', notification_type: 'gc_alert',
  trip_id: null, title: 'Travel message', body: 'Message from your travel team', category: 'gc_alert',
  priority: 'normal', payload: {}, deep_link_path: '/phone-alerts', available_at: '2026-09-15T00:00:00Z', expires_at: null, read_at: null };
const page = { items: [alert], next_cursor: null, unread_count: 1 };
let client: QueryClient;
const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
beforeEach(() => {
  jest.clearAllMocks();
  jest.mocked(apiRequest).mockReset();
  useSessionStore.getState().setSession(session);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false, gcTime: 0 } } });
  jest.mocked(apiRequest).mockResolvedValue(page);
});
afterEach(async () => { await cleanup(); client.clear(); useSessionStore.getState().clear(); });

test.each(['passenger', 'client_manager', 'coordinator'] as const)('loads the %s inbox without a selected trip', async (role) => {
  useSessionStore.getState().setSession({ ...session, principal: { ...session.principal, principalType: role } });
  const { result } = await renderHook(usePhoneAlerts, { wrapper });
  await waitFor(() => expect(result.current.items).toEqual([alert]));
  expect(apiRequest).toHaveBeenCalledWith('/mobile/notifications?limit=100&notification_type=gc_alert',
    expect.objectContaining({ signal: expect.any(AbortSignal) }));
});

test('paginates and deduplicates authored alerts without mixing announcement rows', async () => {
  jest.mocked(apiRequest).mockResolvedValueOnce({ ...page, next_cursor: 'safe-cursor' })
    .mockResolvedValueOnce({ ...page, items: [alert, { ...alert, id: 'other', notification_type: 'announcement' }] });
  const { result } = await renderHook(usePhoneAlerts, { wrapper });
  await waitFor(() => expect(result.current.hasNextPage).toBe(true));
  await act(async () => { await result.current.fetchNextPage(); });
  expect(result.current.items).toEqual([alert]);
  expect(apiRequest).toHaveBeenLastCalledWith('/mobile/notifications?limit=100&notification_type=gc_alert&cursor=safe-cursor', expect.any(Object));
});

test('marks only the selected recipient row read using the authenticated endpoint', async () => {
  const { result } = await renderHook(usePhoneAlerts, { wrapper });
  await waitFor(() => expect(result.current.items).toHaveLength(1));
  jest.mocked(apiRequest).mockResolvedValueOnce({ id: alert.id, read_at: '2026-09-15T01:00:00Z' });
  await act(async () => { result.current.markRead(alert.id); });
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(`/mobile/notifications/${alert.id}/read`,
    expect.objectContaining({ method: 'POST', body: {}, signal: expect.any(AbortSignal) })));
  await waitFor(() => expect(result.current.markingRead).toBe(false));
});

test('late results cannot leak into a replacement account inbox', async () => {
  let resolve!: (value: unknown) => void;
  jest.mocked(apiRequest).mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  const { result } = await renderHook(usePhoneAlerts, { wrapper });
  await waitFor(() => expect(apiRequest).toHaveBeenCalledTimes(1));
  jest.mocked(apiRequest).mockResolvedValue({ ...page, items: [], unread_count: 0 });
  await act(async () => {
    useSessionStore.getState().setSession({ ...session, sessionId: 'session-b',
      principal: { ...session.principal, accountId: 'account-b' } });
    resolve(page);
  });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.items).toEqual([]);
});

test.each([null, { ...session, accessToken: null, networkMode: 'offline' as const }])(
  'does not request the inbox without an online authenticated session', async (currentSession) => {
    if (currentSession) useSessionStore.getState().setSession(currentSession); else useSessionStore.getState().clear();
    const { result } = await renderHook(usePhoneAlerts, { wrapper });
    expect(result.current.items).toEqual([]);
    expect(apiRequest).not.toHaveBeenCalled();
  },
);
