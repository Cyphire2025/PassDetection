/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories load mocked host components after hoisting. */
import { act, render, waitFor } from '@testing-library/react-native';
import { Image } from 'expo-image';
import { AppState, Text, type AppStateStatus } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';
import { clearOfflineAuthorizationBootAnchor } from '@/core/auth/offline-authorization';
import type { MobileSession } from '@/core/auth/types';
import { purgeTemporaryViews } from '@/core/storage/vault';
import { purgeManagerDocumentPreviews } from '@/features/manager/data/manager-document-preview';

import { AppProviders } from '../app-providers';

jest.mock('@tanstack/react-query', () => {
  return {
    QueryClientProvider: ({ children }: { children: import('react').ReactNode }) => children,
  };
});
jest.mock('expo-image', () => ({
  Image: {
    clearDiskCache: jest.fn(),
    clearMemoryCache: jest.fn(),
  },
}));
jest.mock('expo-splash-screen', () => ({ hideAsync: jest.fn(async () => undefined) }));
jest.mock('react-native-gesture-handler', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return {
    GestureHandlerRootView: ({ children }: { children: React.ReactNode }) => (
      React.createElement(MockView, null, children)
    ),
  };
});
jest.mock('react-native-safe-area-context', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return {
    SafeAreaProvider: ({ children }: { children: React.ReactNode }) => (
      React.createElement(MockView, null, children)
    ),
  };
});
jest.mock('@/core/auth/application-bootstrap', () => ({
  bootstrapApplicationSession: jest.fn(async () => ({ status: 'anonymous' })),
}));
jest.mock('@/core/auth/offline-authorization', () => ({
  clearOfflineAuthorizationBootAnchor: jest.fn(),
}));
jest.mock('@/core/demo/demo-mode', () => ({ isDemoMode: () => false }));
jest.mock('@/core/notifications/notification-runtime', () => ({ NotificationRuntime: () => null }));
jest.mock('@/core/query/query-client', () => ({ mobileQueryClient: { clear: jest.fn() } }));
jest.mock('@/core/query/react-native-query-runtime', () => ({ ReactNativeQueryRuntime: () => null }));
jest.mock('@/core/storage/vault', () => ({ purgeTemporaryViews: jest.fn(async () => undefined) }));
jest.mock('@/core/sync/sync-runtime', () => ({ SyncRuntime: () => null }));
jest.mock('@/features/manager/data/manager-document-preview', () => ({
  purgeManagerDocumentPreviews: jest.fn(async () => undefined),
}));
jest.mock('@/features/my-photos/downloads/photo-download-runtime', () => ({
  MyPhotosCapabilityRuntime: () => null,
}));

const mockedPurgeManagerPreviews = jest.mocked(purgeManagerDocumentPreviews);
const mockedPurgeTemporaryViews = jest.mocked(purgeTemporaryViews);
const mockedClearBootAnchor = jest.mocked(clearOfflineAuthorizationBootAnchor);
const mockClearDiskCache = jest.mocked(Image.clearDiskCache);
const mockClearMemoryCache = jest.mocked(Image.clearMemoryCache);

const SESSION: MobileSession = {
  accessToken: 'access-token',
  accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
  sessionId: '33333333-3333-4333-8333-333333333333',
  networkMode: 'online',
  principal: {
    id: '22222222-2222-4222-8222-222222222222',
    accountId: '22222222-2222-4222-8222-222222222222',
    principalType: 'client_manager',
    agencyId: '11111111-1111-4111-8111-111111111111',
    displayName: 'Manager One',
    email: null,
    phoneNumber: null,
    forcePasswordChange: false,
  },
};

beforeEach(() => {
  jest.clearAllMocks();
  mockClearDiskCache.mockResolvedValue(false);
  mockClearMemoryCache.mockResolvedValue(false);
  useSessionStore.getState().clear();
});

afterEach(() => {
  useSessionStore.getState().clear();
  jest.restoreAllMocks();
});

test('purges manager plaintext on startup, background, login, and logout boundaries', async () => {
  let emitAppState: ((state: AppStateStatus) => void) | undefined;
  const removeListener = jest.fn();
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, listener) => {
    emitAppState = listener;
    return { remove: removeListener };
  });

  const screen = await render(
    <AppProviders>
      <Text>Application</Text>
    </AppProviders>,
  );
  await waitFor(() => expect(mockedPurgeManagerPreviews).toHaveBeenCalledTimes(1));
  expect(mockedPurgeTemporaryViews).toHaveBeenCalledTimes(1);

  await act(async () => {
    emitAppState?.('background');
    await Promise.resolve();
  });
  await waitFor(() => expect(mockedPurgeManagerPreviews).toHaveBeenCalledTimes(2));
  expect(mockedClearBootAnchor).toHaveBeenCalledTimes(1);

  await act(async () => {
    useSessionStore.getState().setSession(SESSION);
    await Promise.resolve();
  });
  await waitFor(() => expect(mockedPurgeManagerPreviews).toHaveBeenCalledTimes(3));

  await act(async () => {
    useSessionStore.getState().clear();
    await Promise.resolve();
  });
  await waitFor(() => expect(mockedPurgeManagerPreviews).toHaveBeenCalledTimes(4));

  await screen.unmount();
  expect(removeListener).toHaveBeenCalledTimes(1);
});

test('keeps a failed privacy cleanup as an obligation and retries it at the next lifecycle boundary', async () => {
  let emitAppState: ((state: AppStateStatus) => void) | undefined;
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, listener) => {
    emitAppState = listener;
    return { remove: jest.fn() };
  });
  mockedPurgeTemporaryViews
    .mockRejectedValueOnce(new Error('temporary filesystem unavailable'))
    .mockResolvedValue(undefined);

  const screen = await render(
    <AppProviders>
      <Text>Application</Text>
    </AppProviders>,
  );
  await waitFor(() => expect(mockedPurgeTemporaryViews).toHaveBeenCalledTimes(1));

  await act(async () => {
    emitAppState?.('background');
    await Promise.resolve();
  });

  await waitFor(() => expect(mockedPurgeTemporaryViews).toHaveBeenCalledTimes(2));
  expect(mockClearDiskCache).toHaveBeenCalledTimes(2);
  await screen.unmount();
});
