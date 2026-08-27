/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories load host components after hoisting. */
import { act, fireEvent, render } from '@testing-library/react-native';
import { router } from 'expo-router';

import { ApiError } from '@/core/api/client';

import { createMyPhotosRemoteImageResolver } from '../../media/photo-image-source';
import { MyPhotosScreen } from '../my-photos-screen';

const mockRefetch = jest.fn();
const mockUseSummary = jest.fn();
let mockSession: Readonly<{
  accessToken: string;
  principal: Readonly<{
    accountId: string;
    agencyId: string;
    passengerId: string;
    principalType: 'passenger';
  }>;
}> | null = null;

jest.mock('expo-router', () => ({
  router: { back: jest.fn(), push: jest.fn() },
}));
jest.mock('lucide-react-native/icons/chevron-left', () => () => null);
jest.mock('lucide-react-native/icons/settings', () => () => null);
jest.mock('@/core/auth/session-store', () => ({
  useSessionStore: (selector: (state: { session: typeof mockSession }) => unknown) => selector({ session: mockSession }),
}));
jest.mock('@/core/observability/mobile-observability', () => ({ recordMobileMetric: jest.fn() }));
jest.mock('@/core/security/sensitive-screen-protection', () => ({ SensitiveScreenProtection: () => null }));
jest.mock('@/design/components/content-state', () => {
  const React = require('react') as typeof import('react');
  const { Text: MockText } = require('react-native') as typeof import('react-native');
  return { ContentLoading: ({ label }: { label: string }) => React.createElement(MockText, null, label) };
});
jest.mock('@/features/trips/hooks/use-trips', () => ({
  useTrips: () => ({
    selectedTripId: '11111111-1111-4111-8111-111111111111',
    selectedTrip: { name: 'Synthetic MICE Trip', timeZone: 'Asia/Kolkata' },
  }),
}));
jest.mock('../../hooks/use-my-photos', () => ({
  useMyPhotosSummary: () => mockUseSummary(),
}));
jest.mock('../../hooks/use-photo-downloads', () => ({
  photoDownloadPlanView: jest.fn(),
  usePhotoDownloads: () => ({
    activatePlan: jest.fn(),
    cancel: jest.fn(),
    pause: jest.fn(),
    planAllMatched: jest.fn(),
    planFilterSelection: jest.fn(),
    planSelected: jest.fn(),
    resume: jest.fn(),
    plan: { isPending: false },
    activate: { isPending: false },
    jobs: { data: [] },
    storage: { data: { activeCount: 0, completedCount: 0, encryptedBytes: 0 } },
  }),
}));
jest.mock('../../media/photo-image-source', () => ({
  createMyPhotosImageCacheScope: jest.fn(() => ({ partition: 'a'.repeat(64) })),
  createMyPhotosRemoteImageResolver: jest.fn(),
}));
jest.mock('../my-photos-gallery', () => ({ MyPhotosGallery: () => null }));
jest.mock('../my-photos-overview', () => ({ MyPhotosOverview: () => null }));
jest.mock('../photo-download-plan-modal', () => ({ PhotoDownloadPlanModal: () => null }));
jest.mock('../photo-download-queue-card', () => ({ PhotoDownloadQueueCard: () => null }));
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
  return {
    PageHeader: ({ title, subtitle }: { title: string; subtitle: string }) => React.createElement(
      MockText,
      { accessibilityRole: 'header' },
      `${title}. ${subtitle}`,
    ),
  };
});
jest.mock('../my-photos-status-panel', () => {
  const React = require('react') as typeof import('react');
  const {
    Pressable: MockPressable,
    Text: MockText,
    View: MockView,
  } = require('react-native') as typeof import('react-native');
  return {
    MyPhotosStatusPanel: ({
      onRefresh,
      presentation,
    }: {
      onRefresh: () => void;
      presentation: { title: string; message: string; action: string };
    }) => React.createElement(
      MockView,
      null,
      React.createElement(MockText, { accessibilityRole: 'alert' }, presentation.title),
      React.createElement(MockText, null, presentation.message),
      presentation.action === 'refresh'
        ? React.createElement(
            MockPressable,
            { accessibilityRole: 'button', accessibilityLabel: 'Try again', onPress: onRefresh },
            React.createElement(MockText, null, 'Try again'),
          )
        : null,
    ),
  };
});

beforeEach(() => {
  jest.clearAllMocks();
  mockSession = null;
  mockUseSummary.mockReturnValue({
    data: undefined,
    error: new ApiError('Service unavailable.', 503, 'SERVICE_UNAVAILABLE', null),
    isError: true,
    isPending: false,
    refetch: mockRefetch,
  });
});

test('keeps the My Photos route and privacy controls visible for a recoverable summary failure', async () => {
  const screen = await render(<MyPhotosScreen />);

  expect(screen.getByRole('header', { name: /My Photos/i })).toBeTruthy();
  expect(screen.getByRole('alert')).toHaveTextContent(/My Photos could not be refreshed/);
  expect(screen.getByRole('button', { name: 'Close' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Storage and privacy' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();

  await fireEvent.press(screen.getByRole('button', { name: 'Storage and privacy' }));
  await fireEvent.press(screen.getByRole('button', { name: 'Try again' }));

  expect(router.push).toHaveBeenCalledWith('/(passenger)/my-photos/storage');
  expect(mockRefetch).toHaveBeenCalledTimes(1);
});

test('clears the screen-scoped image resolver when the My Photos route unmounts', async () => {
  const clear = jest.fn(async () => undefined);
  jest.mocked(createMyPhotosRemoteImageResolver).mockReturnValue({
    clear,
    resolve: jest.fn(async () => null),
  });
  mockSession = {
    accessToken: 'private-access-token',
    principal: {
      accountId: '22222222-2222-4222-8222-222222222222',
      agencyId: '11111111-1111-4111-8111-111111111111',
      passengerId: '33333333-3333-4333-8333-333333333333',
      principalType: 'passenger',
    },
  };

  const screen = await render(<MyPhotosScreen />);
  expect(createMyPhotosRemoteImageResolver).toHaveBeenCalledTimes(1);
  await act(() => screen.unmount());
  expect(clear).toHaveBeenCalledTimes(1);
});
