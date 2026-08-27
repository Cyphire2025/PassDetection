import { fireEvent, render } from '@testing-library/react-native';
import { onlineManager } from '@tanstack/react-query';
import { router } from 'expo-router';

import { recordMobileMetric } from '@/core/observability/mobile-observability';

import { MyPhotosTripCard } from '../my-photos-trip-card';

let mockExperienceState = 'matches_ready';
let mockFeatureEnabled = true;
let mockSummarySource: 'network' | 'offline' = 'network';
let mockSummaryError: Error | null = null;

jest.mock('expo-router', () => ({
  router: { push: jest.fn() },
}));

jest.mock('lucide-react-native/icons/images', () => () => null);

jest.mock('@/core/observability/mobile-observability', () => ({
  recordMobileMetric: jest.fn(),
}));

jest.mock('../../hooks/use-my-photos', () => ({
  useMyPhotosSummary: () => ({
    data: {
      source: mockSummarySource,
      value: {
        capability: { feature_enabled: mockFeatureEnabled },
        experience_state: mockExperienceState,
      },
    },
    error: mockSummaryError,
  }),
}));

beforeEach(() => {
  onlineManager.setOnline(true);
  mockExperienceState = 'matches_ready';
  mockFeatureEnabled = true;
  mockSummarySource = 'network';
  mockSummaryError = null;
  jest.mocked(router.push).mockClear();
  jest.mocked(recordMobileMetric).mockClear();
});

test('keeps My Photos discoverable from the selected trip and records privacy-safe opening telemetry', async () => {
  const screen = await render(<MyPhotosTripCard tripId="11111111-1111-4111-8111-111111111111" />);

  await fireEvent.press(screen.getByRole('button', { name: /Open My Photos/i }));

  expect(router.push).toHaveBeenCalledWith('/(passenger)/my-photos');
  expect(recordMobileMetric).toHaveBeenCalledWith(
    'my_photos_open',
    1,
    { trigger: 'manual', outcome: 'success' },
  );
});

test('communicates the provider-not-configured state without implying local liveness', async () => {
  mockExperienceState = 'provider_not_configured';
  const screen = await render(<MyPhotosTripCard tripId="11111111-1111-4111-8111-111111111111" />);

  expect(screen.getByText('Face Scan is not available yet.')).toBeTruthy();
});

test('stays subscribed while hidden and appears after the server enables My Photos', async () => {
  mockFeatureEnabled = false;
  mockExperienceState = 'feature_unavailable';
  const screen = await render(
    <MyPhotosTripCard tripId="11111111-1111-4111-8111-111111111111" />,
  );

  expect(screen.queryByRole('button', { name: /Open My Photos/i })).toBeNull();

  mockFeatureEnabled = true;
  mockExperienceState = 'matches_ready';
  await screen.rerender(
    <MyPhotosTripCard tripId="11111111-1111-4111-8111-111111111111" />,
  );

  expect(screen.getByRole('button', { name: /Open My Photos/i })).toBeTruthy();
});

test('fails closed for an offline cached or errored capability', async () => {
  mockSummarySource = 'offline';
  const screen = await render(
    <MyPhotosTripCard tripId="11111111-1111-4111-8111-111111111111" />,
  );
  expect(screen.queryByRole('button', { name: /Open My Photos/i })).toBeNull();

  mockSummarySource = 'network';
  mockSummaryError = new Error('refetch failed');
  await screen.rerender(
    <MyPhotosTripCard tripId="11111111-1111-4111-8111-111111111111" />,
  );
  expect(screen.queryByRole('button', { name: /Open My Photos/i })).toBeNull();
});
