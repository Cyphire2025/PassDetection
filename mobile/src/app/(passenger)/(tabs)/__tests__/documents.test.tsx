/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories must load mocked host components after hoisting. */
import { act, fireEvent, render, waitFor } from '@testing-library/react-native';
import PassengerDocumentsScreen from '../documents';

const mockPrefetch = jest.fn();
const mockCacheDocument = jest.fn();
const mockUseDocuments = jest.fn();
const mockUseTrips = jest.fn();

jest.mock('expo-router', () => ({ router: { push: jest.fn() } }));
jest.mock('lucide-react-native/icons/circle-check-big', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(MockView) };
});
jest.mock('lucide-react-native/icons/cloud-download', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(MockView) };
});
jest.mock('lucide-react-native/icons/file-clock', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(MockView) };
});
jest.mock('lucide-react-native/icons/file-text', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(MockView) };
});
jest.mock('lucide-react-native/icons/lock-keyhole', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(MockView) };
});
jest.mock('@/features/content/data/content-repository', () => ({
  cacheDocument: (...args: unknown[]) => mockCacheDocument(...args),
  prefetchPassengerOfflineDocuments: (...args: unknown[]) => mockPrefetch(...args),
}));
jest.mock('@/features/content/data/passenger-document-policy', () => {
  const actual = jest.requireActual('@/features/content/data/passenger-document-policy');
  return { ...actual, shouldPrefetchPassengerDocument: () => true };
});
jest.mock('@/features/content/hooks/use-content', () => ({
  useDocuments: (...args: unknown[]) => mockUseDocuments(...args),
}));
jest.mock('@/features/trips/hooks/use-trips', () => ({
  useTrips: () => mockUseTrips(),
}));
jest.mock('@/design/components/content-state', () => {
  const React = require('react') as typeof import('react');
  const { Text: MockText } = require('react-native') as typeof import('react-native');
  const State = ({ label, message }: { label?: string; message?: string }) => (
    React.createElement(MockText, null, label ?? message ?? '')
  );
  return { ContentError: State, ContentLoading: State };
});
jest.mock('@/design/components/glass-card', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return {
    GlassCard: ({ children }: { children: React.ReactNode }) => React.createElement(MockView, null, children),
  };
});
jest.mock('@/design/components/page-header', () => {
  const React = require('react') as typeof import('react');
  const { Text: MockText } = require('react-native') as typeof import('react-native');
  return { PageHeader: ({ title }: { title: string }) => React.createElement(MockText, null, title) };
});
jest.mock('@/design/components/screen', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return {
    Screen: ({ children }: { children: React.ReactNode }) => React.createElement(MockView, null, children),
  };
});

const document = {
  id: '44444444-4444-4444-8444-444444444444',
  trip_id: '33333333-3333-4333-8333-333333333333',
  passenger_id: '22222222-2222-4222-8222-222222222222',
  scope: 'personal' as const,
  category: 'passport',
  display_name: 'Passport front',
  content_type: 'image/jpeg' as const,
  size_bytes: 1024,
  version: 1,
  checksum_sha256: 'a'.repeat(64),
  offline_available: true,
  metadata_state: 'ready' as const,
  updated_at: '2026-08-03T00:00:00.000Z',
  revoked_at: null,
  offline: false,
  offlineVersion: null,
};

beforeEach(() => {
  jest.clearAllMocks();
  mockUseTrips.mockReturnValue({ selectedTripId: document.trip_id });
});

test('automatic document preparation stays silent and never drives pull-to-refresh state', async () => {
  let completePrefetch!: (result: {
    total: number;
    completed: number;
    failed: number;
    currentDocumentName: string | null;
  }) => void;
  mockPrefetch.mockReturnValue(new Promise((resolve) => {
    completePrefetch = resolve;
  }));
  const refetch = jest.fn(async () => undefined);
  mockUseDocuments.mockReturnValue({
    data: { items: [document] },
    isPending: false,
    isError: false,
    isRefetching: false,
    refetch,
  });

  const screen = await render(<PassengerDocumentsScreen />);
  await waitFor(() => expect(mockPrefetch).toHaveBeenCalledTimes(1));

  expect(screen.queryByText('Securing new documents for offline use')).toBeNull();

  await act(async () => {
    completePrefetch({ total: 1, completed: 1, failed: 0, currentDocumentName: null });
    await Promise.resolve();
  });

  expect(refetch).toHaveBeenCalledTimes(1);
  expect(mockPrefetch).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('Securing new documents for offline use')).toBeNull();
});

test('automatic document failures remain silent for later background or manual retry', async () => {
  mockPrefetch.mockResolvedValue({
    total: 1,
    completed: 0,
    failed: 1,
    currentDocumentName: null,
  });
  const refetch = jest.fn(async () => undefined);
  mockUseDocuments.mockReturnValue({
    data: { items: [document] },
    isPending: false,
    isError: false,
    isRefetching: false,
    refetch,
  });

  const screen = await render(<PassengerDocumentsScreen />);
  await waitFor(() => expect(mockPrefetch).toHaveBeenCalledTimes(1));

  expect(refetch).not.toHaveBeenCalled();
  expect(screen.queryByText(/could not be saved offline yet/i)).toBeNull();
  expect(screen.queryByText('Securing new documents for offline use')).toBeNull();
});

test('pull-to-refresh performs one bounded metadata and offline preparation cycle', async () => {
  mockPrefetch.mockResolvedValue({
    total: 0,
    completed: 0,
    failed: 0,
    currentDocumentName: null,
  });
  const refetch = jest.fn(async () => undefined);
  mockUseDocuments.mockReturnValue({
    data: { items: [] },
    isPending: false,
    isError: false,
    isRefetching: false,
    refetch,
  });

  const screen = await render(<PassengerDocumentsScreen />);
  await fireEvent(screen.getByTestId('passenger-documents-list'), 'refresh');

  await waitFor(() => expect(refetch).toHaveBeenCalledTimes(2));
  expect(mockPrefetch).toHaveBeenCalledTimes(1);
  expect(mockPrefetch).toHaveBeenCalledWith(document.trip_id);
});
