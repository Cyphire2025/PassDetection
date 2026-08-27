/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories load host components after hoisting. */
import { render } from '@testing-library/react-native';

import { MyPhotosStorageScreen } from '../my-photos-storage-screen';

const mockSummaryRefetch = jest.fn();

jest.mock('expo-router', () => ({ router: { back: jest.fn(), push: jest.fn() } }));
jest.mock('lucide-react-native/icons/chevron-left', () => () => null);
jest.mock('lucide-react-native/icons/eraser', () => () => null);
jest.mock('lucide-react-native/icons/scan-face', () => () => null);
jest.mock('lucide-react-native/icons/shield-x', () => () => null);
jest.mock('lucide-react-native/icons/trash-2', () => () => null);
jest.mock('@/design/components/content-state', () => {
  const React = require('react') as typeof import('react');
  const { Text: MockText } = require('react-native') as typeof import('react-native');
  return { ContentLoading: ({ label }: { label: string }) => React.createElement(MockText, null, label) };
});
jest.mock('@/core/auth/session-store', () => ({
  useSessionStore: (selector: (state: { session: null }) => unknown) => selector({ session: null }),
}));
jest.mock('@/features/trips/hooks/use-trips', () => ({
  useTrips: () => ({
    selectedTripId: '11111111-1111-4111-8111-111111111111',
    selectedTrip: { name: 'Synthetic MICE Trip', timeZone: 'Asia/Kolkata' },
  }),
}));
jest.mock('../../hooks/use-my-photos', () => ({
  useMyPhotosMutations: () => ({
    deleteEnrollment: { isPending: false, mutateAsync: jest.fn() },
  }),
  useMyPhotosSummary: () => ({
    data: undefined,
    error: new Error('Service unavailable.'),
    isError: true,
    isPending: false,
    refetch: mockSummaryRefetch,
  }),
}));
jest.mock('../../hooks/use-photo-downloads', () => ({
  useCompletedPhotoDownloadsPage: () => ({
    data: { items: [], nextCursor: null, previousCursor: null },
    isError: false,
    isFetching: false,
    isPending: false,
    refetch: jest.fn(),
  }),
  usePhotoDownloads: () => ({
    cancel: jest.fn(),
    clearAllStorage: jest.fn(),
    pause: jest.fn(),
    removeAllCompleted: jest.fn(),
    remove: jest.fn(),
    resume: jest.fn(),
    clearStorage: { isPending: false },
    control: { isPending: false },
    jobs: { data: [] },
    removeAll: { isPending: false },
    storage: { data: { activeCount: 0, completedCount: 2, encryptedBytes: 2048 } },
  }),
}));
jest.mock('../downloaded-photos-card', () => {
  const React = require('react') as typeof import('react');
  const { Text: MockText } = require('react-native') as typeof import('react-native');
  return { DownloadedPhotosCard: () => React.createElement(MockText, null, 'Downloaded photos') };
});
jest.mock('../photo-download-queue-card', () => {
  const React = require('react') as typeof import('react');
  const { Text: MockText } = require('react-native') as typeof import('react-native');
  return { PhotoDownloadQueueCard: () => React.createElement(MockText, null, 'Download queue') };
});
jest.mock('@/design/components/screen', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return {
    Screen: ({ children }: { children: React.ReactNode }) => React.createElement(MockView, null, children),
  };
});
jest.mock('@/design/components/page-header', () => {
  const React = require('react') as typeof import('react');
  const { Text: MockText } = require('react-native') as typeof import('react-native');
  return { PageHeader: ({ title }: { title: string }) => React.createElement(MockText, null, title) };
});
jest.mock('../my-photos-status-panel', () => {
  const React = require('react') as typeof import('react');
  const { Text: MockText } = require('react-native') as typeof import('react-native');
  return {
    MyPhotosStatusPanel: ({ presentation }: { presentation: { title: string } }) => React.createElement(
      MockText,
      { accessibilityRole: 'alert' },
      presentation.title,
    ),
  };
});

test('preserves local privacy cleanup when the authoritative My Photos summary is unavailable', async () => {
  const screen = await render(<MyPhotosStorageScreen />);

  expect(screen.getAllByText('Storage and privacy').length).toBeGreaterThan(0);
  expect(screen.getAllByRole('alert').some((node) => (
    String(node.props.children).includes('My Photos could not be refreshed')
  ))).toBe(true);
  expect(screen.getByRole('button', { name: /Remove downloaded copies/i }).props.accessibilityState)
    .toMatchObject({ disabled: false });
  expect(screen.getByRole('button', { name: /Clear My Photos storage/i }).props.accessibilityState)
    .toMatchObject({ disabled: false });
  expect(screen.getByRole('button', { name: /Delete Face Scan/i }).props.accessibilityState)
    .toMatchObject({ disabled: true });
  expect(screen.getByRole('button', { name: /Remove my face-search data/i }).props.accessibilityState)
    .toMatchObject({ disabled: true });
});
