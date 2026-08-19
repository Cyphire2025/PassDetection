/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories load mocked host components after hoisting. */
import { act, fireEvent, render, waitFor } from '@testing-library/react-native';
import { router } from 'expo-router';
import { AppState, type AppStateStatus } from 'react-native';

import { ApiError } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import {
  decryptDocumentForViewing,
  LocalOfflineCiphertextError,
  releaseTemporaryView,
  removeTemporaryView,
} from '@/core/storage/vault';
import {
  cacheDocument,
  getDocument,
  recordOfflineDocumentOpened,
} from '@/features/content/data/content-repository';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import SecureDocumentScreen from '../[id]';

jest.mock('expo-router', () => ({
  router: { back: jest.fn() },
  useLocalSearchParams: () => ({
    id: '44444444-4444-4444-8444-444444444444',
    tripId: '55555555-5555-4555-8555-555555555555',
  }),
}));
jest.mock('expo-image', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  const EventView = MockView as React.ComponentType<Record<string, unknown>>;
  return {
    Image: (props: Record<string, unknown>) => React.createElement(EventView, {
      ...props,
      testID: 'image-viewer',
    }),
  };
});
jest.mock('react-native-pdf', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  const EventView = MockView as React.ComponentType<Record<string, unknown>>;
  return {
    __esModule: true,
    default: (props: { onError?: () => void; source?: unknown }) => React.createElement(EventView, {
      ...props,
      testID: 'pdf-viewer',
    }),
  };
});
jest.mock('@/core/storage/vault', () => ({
  decryptDocumentForViewing: jest.fn(),
  isLocalOfflineCiphertextError: jest.fn((error: unknown) => (
    typeof error === 'object' && error !== null && 'code' in error
    && error.code === 'LOCAL_OFFLINE_CIPHERTEXT_CORRUPT'
  )),
  LocalOfflineCiphertextError: class LocalOfflineCiphertextError extends Error {
    readonly code = 'LOCAL_OFFLINE_CIPHERTEXT_CORRUPT';
  },
  releaseTemporaryView: jest.fn(),
  removeTemporaryView: jest.fn(),
}));
jest.mock('@/core/security/sensitive-screen-protection', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return {
    SensitiveScreenProtection: ({ protectionKey }: { protectionKey: string }) => (
      React.createElement(MockView, {
        accessibilityLabel: protectionKey,
        testID: 'sensitive-screen-protection',
      })
    ),
  };
});
jest.mock('@/features/content/data/content-repository', () => ({
  cacheDocument: jest.fn(),
  getDocument: jest.fn(),
  recordOfflineDocumentOpened: jest.fn(),
}));
jest.mock('@/design/components/glass-card', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return {
    GlassCard: ({ children }: { children: React.ReactNode }) => React.createElement(MockView, null, children),
  };
});
jest.mock('@/design/components/primary-button', () => {
  const React = require('react') as typeof import('react');
  const { Text: MockText, View: MockView } = require('react-native') as typeof import('react-native');
  const EventView = MockView as React.ComponentType<Record<string, unknown>>;
  return {
    PrimaryButton: ({ label, onPress }: { label: string; onPress?: () => void }) => (
      React.createElement(
        EventView,
        { accessibilityRole: 'button', accessibilityLabel: label, onPress },
        React.createElement(MockText, null, label),
      )
    ),
  };
});
jest.mock('@/design/components/screen', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return {
    Screen: ({ children }: { children: React.ReactNode }) => React.createElement(MockView, null, children),
  };
});

const mockedCacheDocument = jest.mocked(cacheDocument);
const mockedDecryptDocument = jest.mocked(decryptDocumentForViewing);
const mockedRecordDocumentOpened = jest.mocked(recordOfflineDocumentOpened);
const mockedGetDocument = jest.mocked(getDocument);
const mockedReleaseTemporary = jest.mocked(releaseTemporaryView);
const mockedRemoveTemporary = jest.mocked(removeTemporaryView);

const SESSION: MobileSession = {
  accessToken: 'access-token',
  accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
  sessionId: '33333333-3333-4333-8333-333333333333',
  networkMode: 'online',
  principal: {
    id: '22222222-2222-4222-8222-222222222222',
    accountId: '22222222-2222-4222-8222-222222222222',
    principalType: 'passenger',
    agencyId: '11111111-1111-4111-8111-111111111111',
    displayName: 'Passenger One',
    email: null,
    phoneNumber: null,
    forcePasswordChange: false,
  },
};

const DOCUMENT = {
  id: '44444444-4444-4444-8444-444444444444',
  trip_id: '55555555-5555-4555-8555-555555555555',
  passenger_id: '22222222-2222-4222-8222-222222222222',
  scope: 'personal' as const,
  category: 'passport',
  display_name: 'Passport',
  content_type: 'application/pdf' as const,
  size_bytes: 1_024,
  version: 1,
  checksum_sha256: 'a'.repeat(64),
  offline_available: true,
  metadata_state: 'ready' as const,
  updated_at: '2029-01-01T00:00:00.000Z',
  revoked_at: null,
  offline: false,
  offlineVersion: null,
};

function temporary(uri: string) {
  return { uri } as Awaited<ReturnType<typeof decryptDocumentForViewing>>;
}

beforeEach(() => {
  jest.clearAllMocks();
  useSessionStore.getState().setSession(SESSION);
  useSelectedTripStore.getState().selectTrip(DOCUMENT.trip_id);
  mockedGetDocument.mockResolvedValue(DOCUMENT);
  mockedCacheDocument.mockResolvedValue(undefined);
  mockedDecryptDocument.mockResolvedValue(temporary('file:///secure/passport.pdf'));
  mockedRecordDocumentOpened.mockResolvedValue(undefined);
});

afterEach(() => {
  useSessionStore.getState().clear();
  useSelectedTripStore.getState().clear();
  jest.restoreAllMocks();
});

test('retries a transient download failure in place and coalesces repeated retry taps', async () => {
  mockedCacheDocument
    .mockRejectedValueOnce(new TypeError('Network request failed'))
    .mockResolvedValueOnce(undefined);

  const screen = await render(<SecureDocumentScreen />);
  await waitFor(() => expect(screen.getByText('Retry')).toBeTruthy());
  const retry = screen.getByLabelText('Retry');
  expect(screen.getByText('Check your connection and try again.')).toBeTruthy();
  expect(screen.queryByText('Network request failed')).toBeNull();

  await act(async () => {
    retry.props.onPress();
    retry.props.onPress();
    await Promise.resolve();
  });

  await waitFor(() => expect(screen.getByTestId('pdf-viewer')).toBeTruthy());
  expect(mockedGetDocument).toHaveBeenCalledTimes(2);
  expect(mockedCacheDocument).toHaveBeenCalledTimes(2);
  expect(mockedDecryptDocument).toHaveBeenCalledTimes(1);
  expect(mockedRecordDocumentOpened).toHaveBeenCalledWith({
    namespace: `${SESSION.principal.agencyId}.${SESSION.principal.accountId}`,
    tripId: DOCUMENT.trip_id,
    documentId: DOCUMENT.id,
    version: DOCUMENT.version,
  });
});

test('cleans a failed renderer temporary file before retrying with a fresh view', async () => {
  const firstTemporary = temporary('file:///secure/first.pdf');
  const secondTemporary = temporary('file:///secure/second.pdf');
  mockedGetDocument.mockResolvedValue({ ...DOCUMENT, offline: true, offlineVersion: 1 });
  mockedDecryptDocument
    .mockResolvedValueOnce(firstTemporary)
    .mockResolvedValueOnce(secondTemporary);

  const screen = await render(<SecureDocumentScreen />);
  await waitFor(() => expect(screen.getByTestId('pdf-viewer')).toBeTruthy());
  const firstViewer = screen.getByTestId('pdf-viewer');
  await fireEvent(firstViewer, 'error');

  expect(mockedRemoveTemporary).toHaveBeenCalledWith(firstTemporary);
  await waitFor(() => expect(mockedDecryptDocument).toHaveBeenCalledTimes(2));
  expect(screen.getByTestId('pdf-viewer')).toBeTruthy();
  expect(mockedCacheDocument).not.toHaveBeenCalled();

  await fireEvent(screen.getByTestId('pdf-viewer'), 'error');
  expect(screen.getByText('The PDF viewer could not render this file.')).toBeTruthy();
});

test('allows a transient decrypt operation to be retried without leaving a dead end', async () => {
  mockedGetDocument.mockResolvedValue({ ...DOCUMENT, offline: true, offlineVersion: 1 });
  mockedDecryptDocument
    .mockRejectedValueOnce(new Error('Secure storage is temporarily unavailable.'))
    .mockResolvedValueOnce(temporary('file:///secure/recovered.pdf'));

  const screen = await render(<SecureDocumentScreen />);
  await waitFor(() => expect(screen.getByText('Retry')).toBeTruthy());
  await fireEvent.press(screen.getByText('Retry'));

  await waitFor(() => expect(screen.getByTestId('pdf-viewer')).toBeTruthy());
  expect(mockedDecryptDocument).toHaveBeenCalledTimes(2);
});

test('keeps revoked or removed documents terminal', async () => {
  mockedGetDocument.mockResolvedValueOnce(null);

  const screen = await render(<SecureDocumentScreen />);

  await waitFor(() => expect(screen.getByText('This document is no longer available.')).toBeTruthy());
  expect(screen.queryByText('Retry')).toBeNull();
  expect(mockedCacheDocument).not.toHaveBeenCalled();
  expect(mockedDecryptDocument).not.toHaveBeenCalled();
});

test('fails closed when locally synchronized metadata marks a document revoked', async () => {
  mockedGetDocument.mockResolvedValueOnce({
    ...DOCUMENT,
    revoked_at: '2029-01-02T00:00:00.000Z',
    offline: true,
    offlineVersion: 1,
  });

  const screen = await render(<SecureDocumentScreen />);

  await waitFor(() => expect(screen.getByText('This document is no longer available.')).toBeTruthy());
  expect(screen.queryByText('Retry')).toBeNull();
  expect(mockedCacheDocument).not.toHaveBeenCalled();
  expect(mockedDecryptDocument).not.toHaveBeenCalled();
});

test('never places a decrypted personal image in the renderer disk cache', async () => {
  mockedGetDocument.mockResolvedValueOnce({
    ...DOCUMENT,
    content_type: 'image/jpeg',
    offline: true,
    offlineVersion: 1,
  });
  mockedDecryptDocument.mockResolvedValueOnce(temporary('file:///secure/passport.jpg'));

  const screen = await render(<SecureDocumentScreen />);

  await waitFor(() => expect(screen.getByTestId('image-viewer')).toBeTruthy());
  expect(screen.getByTestId('image-viewer').props.cachePolicy).toBe('none');
  expect(screen.getByTestId('sensitive-screen-protection').props.accessibilityLabel)
    .toBe('secure-document-viewer');
});

test('repairs a locally corrupted registered copy and retries decryption once', async () => {
  mockedGetDocument.mockResolvedValueOnce({ ...DOCUMENT, offline: true, offlineVersion: 1 });
  mockedDecryptDocument
    .mockRejectedValueOnce(new LocalOfflineCiphertextError())
    .mockResolvedValueOnce(temporary('file:///secure/repaired.pdf'));

  const screen = await render(<SecureDocumentScreen />);

  await waitFor(() => expect(screen.getByTestId('pdf-viewer')).toBeTruthy());
  expect(mockedCacheDocument).toHaveBeenCalledTimes(1);
  expect(mockedCacheDocument).toHaveBeenCalledWith(
    expect.objectContaining({ id: DOCUMENT.id }),
    undefined,
    expect.any(AbortSignal),
    'required',
  );
  expect(mockedDecryptDocument).toHaveBeenCalledTimes(2);
});

test('keeps a provider checksum mismatch terminal instead of treating it as local repair', async () => {
  mockedCacheDocument.mockRejectedValueOnce(
    new Error('Downloaded document checksum did not match its metadata.'),
  );

  const screen = await render(<SecureDocumentScreen />);

  await waitFor(() => expect(screen.getByText('Document unavailable')).toBeTruthy());
  expect(screen.queryByText('Retry')).toBeNull();
  expect(mockedDecryptDocument).not.toHaveBeenCalled();
});

test('keeps a missing deployment route retryable without deleting advertised metadata', async () => {
  mockedCacheDocument.mockRejectedValueOnce(
    new ApiError('Not Found', 404, 'HTTP_404', null),
  );

  const screen = await render(<SecureDocumentScreen />);

  await waitFor(() => expect(screen.getByText('Retry')).toBeTruthy());
  expect(screen.getByText('The document service is temporarily unavailable. Try again.')).toBeTruthy();
  expect(mockedGetDocument).toHaveBeenCalledTimes(1);
  expect(mockedDecryptDocument).not.toHaveBeenCalled();
});

test('aborts an active document transfer when the viewer unmounts', async () => {
  let resolveCache!: () => void;
  mockedCacheDocument.mockReturnValueOnce(new Promise<void>((resolve) => {
    resolveCache = resolve;
  }));

  const screen = await render(<SecureDocumentScreen />);
  await waitFor(() => expect(mockedCacheDocument).toHaveBeenCalledTimes(1));
  const signal = mockedCacheDocument.mock.calls[0]?.[2];
  expect(signal?.aborted).toBe(false);

  await screen.unmount();

  expect(signal?.aborted).toBe(true);
  await act(async () => {
    resolveCache();
    await Promise.resolve();
  });
  expect(mockedDecryptDocument).not.toHaveBeenCalled();
});

test('retains the verified foreground preview and goes back to the exact previous screen when closed', async () => {
  const openedTemporary = temporary('file:///secure/close-me.pdf');
  mockedGetDocument.mockResolvedValueOnce({ ...DOCUMENT, offline: true, offlineVersion: 1 });
  mockedDecryptDocument.mockResolvedValueOnce(openedTemporary);

  const screen = await render(<SecureDocumentScreen />);
  await waitFor(() => expect(screen.getByTestId('pdf-viewer')).toBeTruthy());
  await fireEvent.press(screen.getByLabelText('Close document'));

  expect(mockedReleaseTemporary).toHaveBeenCalledWith(openedTemporary);
  expect(mockedRemoveTemporary).not.toHaveBeenCalledWith(openedTemporary);
  expect(router.back).toHaveBeenCalledTimes(1);
});

test('removes plaintext while inactive and transparently opens a fresh view on return', async () => {
  let emitAppState: ((state: AppStateStatus) => void) | undefined;
  const removeListener = jest.fn();
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, listener) => {
    emitAppState = listener;
    return { remove: removeListener };
  });
  const firstTemporary = temporary('file:///secure/first.pdf');
  const secondTemporary = temporary('file:///secure/second.pdf');
  mockedGetDocument.mockResolvedValue({ ...DOCUMENT, offline: true, offlineVersion: 1 });
  mockedDecryptDocument
    .mockResolvedValueOnce(firstTemporary)
    .mockResolvedValueOnce(secondTemporary);

  const screen = await render(<SecureDocumentScreen />);
  await waitFor(() => expect(screen.getByTestId('pdf-viewer')).toBeTruthy());

  await act(async () => {
    emitAppState?.('background');
    await Promise.resolve();
  });
  expect(mockedRemoveTemporary).toHaveBeenCalledWith(firstTemporary);
  expect(screen.queryByTestId('pdf-viewer')).toBeNull();

  await act(async () => {
    emitAppState?.('active');
    await Promise.resolve();
  });
  await waitFor(() => expect(mockedDecryptDocument).toHaveBeenCalledTimes(2));
  expect(screen.getByTestId('pdf-viewer').props.source).toEqual({
    uri: secondTemporary.uri,
    cache: false,
  });

  await screen.unmount();
  expect(removeListener).toHaveBeenCalledTimes(1);
});
