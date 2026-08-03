import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react-native';
import type { PropsWithChildren } from 'react';
import { useMemo } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';

import { usePersistentQueryHydration } from '../use-persistent-query-hydration';

const session = (accountId: string, sessionId = `session-${accountId}`): MobileSession => ({
  accessToken: `access-${accountId}`,
  accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
  sessionId,
  networkMode: 'online',
  principal: {
    id: accountId,
    accountId,
    principalType: 'passenger',
    agencyId: 'agency',
    passengerId: `passenger-${accountId}`,
    displayName: 'Passenger',
    email: null,
    phoneNumber: null,
    forcePasswordChange: false,
  },
});

const wrapperFor = (client: QueryClient) => function QueryWrapper({ children }: PropsWithChildren) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

describe('usePersistentQueryHydration', () => {
  beforeEach(() => {
    useSessionStore.getState().setSession(session('account-a'));
  });

  afterEach(() => {
    useSessionStore.getState().clear();
  });

  it('places the persisted snapshot in React Query before opening the network gate', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { gcTime: 0, retry: false } } });
    const queryKey = ['resource', 'trip-a', 'agency.account-a'] as const;
    let resolveCache!: (value: { source: string }) => void;
    let resolveNetwork!: (value: { source: string }) => void;
    let valueObservedAtNetworkStart: unknown;
    const load = jest.fn(() => new Promise<{ source: string }>((resolve) => {
      resolveCache = resolve;
    }));
    const network = jest.fn(() => {
      valueObservedAtNetworkStart = client.getQueryData(queryKey);
      return new Promise<{ source: string }>((resolve) => {
        resolveNetwork = resolve;
      });
    });

    const { result, unmount } = await renderHook(() => {
      const hydrated = usePersistentQueryHydration({
        accountKey: 'agency.account-a',
        hydrationKey: 'resource:trip-a',
        queryKey,
        load,
      });
      return useQuery({ queryKey, queryFn: network, enabled: hydrated });
    }, { wrapper: wrapperFor(client) });

    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    expect(network).not.toHaveBeenCalled();

    await act(async () => {
      resolveCache({ source: 'persistent' });
    });
    await waitFor(() => expect(network).toHaveBeenCalledTimes(1));
    expect(valueObservedAtNetworkStart).toEqual({ source: 'persistent' });
    expect(result.current.data).toEqual({ source: 'persistent' });

    await act(async () => {
      resolveNetwork({ source: 'network' });
    });
    await waitFor(() => expect(result.current.data).toEqual({ source: 'network' }));
    await unmount();
    client.clear();
  });

  it('uses the network as recovery only after an unreadable cache has settled', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { gcTime: 0, retry: false } } });
    const queryKey = ['resource', 'trip-a', 'agency.account-a'] as const;
    let rejectCache!: (error: Error) => void;
    const load = jest.fn(() => new Promise<never>((_resolve, reject) => {
      rejectCache = reject;
    }));
    const network = jest.fn(async () => ({ source: 'network' }));

    const { result, unmount } = await renderHook(() => {
      const hydrated = usePersistentQueryHydration({
        accountKey: 'agency.account-a',
        hydrationKey: 'resource:trip-a',
        queryKey,
        load,
      });
      return useQuery({ queryKey, queryFn: network, enabled: hydrated });
    }, { wrapper: wrapperFor(client) });

    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    expect(network).not.toHaveBeenCalled();
    await act(async () => {
      rejectCache(new Error('sqlite unavailable'));
    });
    await waitFor(() => expect(result.current.data).toEqual({ source: 'network' }));
    expect(network).toHaveBeenCalledTimes(1);
    await unmount();
    client.clear();
  });

  it('discards a late cache result after the authenticated account changes', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const resolutions = new Map<string, (value: { account: string }) => void>();
    const load = jest.fn((accountKey: string) => new Promise<{ account: string }>((resolve) => {
      resolutions.set(accountKey, resolve);
    }));

    const { result, rerender, unmount } = await renderHook(
      ({ accountKey }: { accountKey: string }) => {
        const queryKey = useMemo(() => ['resource', accountKey] as const, [accountKey]);
        const loadForAccount = useMemo(() => () => load(accountKey), [accountKey]);
        return usePersistentQueryHydration({
          accountKey,
          hydrationKey: 'resource',
          queryKey,
          load: loadForAccount,
        });
      },
      {
        initialProps: { accountKey: 'agency.account-a' },
        wrapper: wrapperFor(client),
      },
    );

    await waitFor(() => expect(load).toHaveBeenCalledWith('agency.account-a'));
    await act(async () => {
      useSessionStore.getState().setSession(session('account-b'));
      await rerender({ accountKey: 'agency.account-b' });
    });
    await waitFor(() => expect(load).toHaveBeenCalledWith('agency.account-b'));

    await act(async () => {
      resolutions.get('agency.account-a')?.({ account: 'account-a' });
    });
    expect(client.getQueryData(['resource', 'agency.account-a'])).toBeUndefined();
    expect(result.current).toBe(false);

    await act(async () => {
      resolutions.get('agency.account-b')?.({ account: 'account-b' });
    });
    await waitFor(() => expect(result.current).toBe(true));
    expect(client.getQueryData(['resource', 'agency.account-b'])).toEqual({ account: 'account-b' });
    await unmount();
    client.clear();
  });

  it('re-gates hydration when a replacement session uses the same account namespace', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const queryKey = ['resource', 'agency.account-a'] as const;
    const resolutions: ((value: { session: string }) => void)[] = [];
    const load = jest.fn(() => new Promise<{ session: string }>((resolve) => {
      resolutions.push(resolve);
    }));

    const { result, unmount } = await renderHook(() => usePersistentQueryHydration({
      accountKey: 'agency.account-a',
      hydrationKey: 'resource',
      queryKey,
      load,
    }), { wrapper: wrapperFor(client) });

    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    await act(async () => {
      useSessionStore.getState().setSession(session('account-a', 'replacement-session'));
    });
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));

    await act(async () => {
      resolutions[0]?.({ session: 'superseded' });
    });
    expect(client.getQueryData(queryKey)).toBeUndefined();
    expect(result.current).toBe(false);

    await act(async () => {
      resolutions[1]?.({ session: 'replacement' });
    });
    await waitFor(() => expect(result.current).toBe(true));
    expect(client.getQueryData(queryKey)).toEqual({ session: 'replacement' });
    await unmount();
    client.clear();
  });
});
