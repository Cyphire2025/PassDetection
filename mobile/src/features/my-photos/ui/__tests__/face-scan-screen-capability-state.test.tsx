/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories load host components after hoisting. */
import { render } from '@testing-library/react-native';

import { FaceScanScreen } from '../face-scan-screen';

const mockSummaryRefetch = jest.fn();

jest.mock('expo-haptics', () => ({
  NotificationFeedbackType: { Success: 'success' },
  notificationAsync: jest.fn(),
}));
jest.mock('expo-camera', () => ({
  CameraView: { isAvailableAsync: jest.fn(async () => true) },
}));
jest.mock('expo-router', () => ({
  router: { back: jest.fn() },
  useNavigation: () => ({ addListener: jest.fn(() => jest.fn()) }),
}));
jest.mock('lucide-react-native/icons/chevron-left', () => () => null);
jest.mock('@/core/observability/mobile-observability', () => ({ recordMobileMetric: jest.fn() }));
jest.mock('@/design/components/content-state', () => {
  const React = require('react') as typeof import('react');
  const { Text: MockText } = require('react-native') as typeof import('react-native');
  return { ContentLoading: ({ label }: { label: string }) => React.createElement(MockText, null, label) };
});
jest.mock('@/features/trips/hooks/use-trips', () => ({
  useTrips: () => ({ selectedTripId: '11111111-1111-4111-8111-111111111111' }),
}));
jest.mock('../../hooks/use-face-scan-controller', () => ({
  useFaceScanController: () => ({
    acceptConsent: jest.fn(),
    cameraUnavailable: jest.fn(),
    cancel: jest.fn(),
    chooseChallenge: jest.fn(),
    continueExplanation: jest.fn(),
    continuePreparation: jest.fn(),
    requestCamera: jest.fn(),
    retry: jest.fn(),
    simulate: jest.fn(),
    start: jest.fn(),
    state: { step: 'explanation' },
    summary: {
      data: {
        value: {
          capability: {
            feature_enabled: true,
            provider_ready: false,
            provider_state: 'not_configured',
          },
        },
      },
      error: null,
      isError: false,
      isPending: false,
      refetch: mockSummaryRefetch,
    },
  }),
}));
jest.mock('@/design/components/screen', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return {
    Screen: ({ children }: { children: React.ReactNode }) => React.createElement(MockView, null, children),
  };
});
jest.mock('../my-photos-status-panel', () => {
  const React = require('react') as typeof import('react');
  const { Text: MockText, View: MockView } = require('react-native') as typeof import('react-native');
  return {
    MyPhotosStatusPanel: ({ presentation }: { presentation: { title: string; message: string } }) => React.createElement(
      MockView,
      null,
      React.createElement(MockText, { accessibilityRole: 'alert' }, presentation.title),
      React.createElement(MockText, null, presentation.message),
    ),
  };
});
jest.mock('../face-scan-running-surface', () => ({ FaceScanRunningSurface: () => null }));
jest.mock('../face-scan-step-content', () => ({ FaceScanStepContent: () => null }));

test('keeps a close path and explicitly fails closed when the provider is not configured', async () => {
  const screen = await render(<FaceScanScreen />);

  expect(screen.getByRole('header', { name: 'Verify your face' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Close' })).toBeTruthy();
  expect(screen.getByRole('alert')).toHaveTextContent('Face Scan is not available yet.');
  expect(screen.getByText(/secure Face Scan provider has not been activated/i)).toBeTruthy();
});
