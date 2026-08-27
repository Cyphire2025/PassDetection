/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories load mocked host components after hoisting. */
import { act, fireEvent, render, waitFor } from '@testing-library/react-native';
import { Text } from 'react-native';

import { offlineAuthorizationReadiness } from '@/core/auth/session-service';
import { attendanceTripQueueStatus } from '@/features/coordinator/data/attendance-queue';
import { loadDeviceEventReadiness } from '@/features/coordinator/data/device-event-readiness';
import { loadCoordinatorReadinessEvidence } from '@/features/coordinator/data/event-readiness';
import { useCoordinatorEventReadiness } from '@/features/coordinator/hooks/use-event-readiness';

import { EventReadinessCard } from '../event-readiness-card';

const NOW = Date.parse('2030-01-02T12:00:00.000Z');
const HORIZON = 8 * 60 * 60_000;

jest.mock('@/core/auth/session-service', () => ({
  offlineAuthorizationReadiness: jest.fn(),
}));
jest.mock('@/core/realtime/realtime-status', () => ({
  useRealtimeStatusStore: (
    selector: (state: { status: 'connected' }) => unknown,
  ) => selector({ status: 'connected' }),
}));
jest.mock('@/features/coordinator/data/attendance-queue', () => ({
  attendanceTripQueueStatus: jest.fn(),
}));
jest.mock('@/features/coordinator/data/device-event-readiness', () => ({
  loadDeviceEventReadiness: jest.fn(),
}));
jest.mock('@/features/coordinator/data/event-readiness', () => {
  const actual = jest.requireActual('@/features/coordinator/data/event-readiness') as object;
  return { ...actual, loadCoordinatorReadinessEvidence: jest.fn() };
});
jest.mock('@/design/components/primary-button', () => {
  const React = require('react') as typeof import('react');
  const { Pressable, Text } = require('react-native') as typeof import('react-native');
  return {
    PrimaryButton: ({ label, onPress }: { label: string; onPress: () => void }) => (
      React.createElement(Pressable, { accessibilityRole: 'button', onPress },
        React.createElement(Text, null, label))
    ),
  };
});

const mockedOfflineAuthorization = jest.mocked(offlineAuthorizationReadiness);
const mockedQueueStatus = jest.mocked(attendanceTripQueueStatus);
const mockedReadinessEvidence = jest.mocked(loadCoordinatorReadinessEvidence);
const mockedDeviceReadiness = jest.mocked(loadDeviceEventReadiness);

async function renderReadinessCard() {
  function ReadinessHarness() {
    const readiness = useCoordinatorEventReadiness({
      activity: {
        id: '22222222-2222-4222-8222-222222222222',
        name: 'Airport departure',
        status: 'active',
        scanned_count: 0,
        assigned_count: 800,
        started_at: new Date(NOW - 60 * 60_000).toISOString(),
        completed_at: null,
        scheduled_starts_at: new Date(NOW - 60 * 60_000).toISOString(),
        scheduled_ends_at: new Date(NOW + 6 * 60 * 60_000).toISOString(),
        schedule_timezone: 'Asia/Kolkata',
        schedule_version: 2,
      },
      cameraGranted: true,
      refreshSignal: '0:0:0',
      tripId: '11111111-1111-4111-8111-111111111111',
    });
    return (
      <>
        <Text testID="capture-gate">{readiness.captureGate}</Text>
        <EventReadinessCard readiness={readiness} />
      </>
    );
  }

  let result!: ReturnType<typeof render>;
  await act(async () => {
    result = render(<ReadinessHarness />);
    await Promise.resolve();
    await Promise.resolve();
  });
  return result;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockedOfflineAuthorization.mockResolvedValue({
    remainingMs: HORIZON + 60_000,
    trustedServerTimeMs: NOW,
  });
  mockedQueueStatus.mockResolvedValue({
    awaitingConfirmation: 0,
    needsReview: 0,
    pending: 0,
    retryable: 0,
    sending: 0,
  });
  mockedReadinessEvidence.mockResolvedValue({
    advertisedRosterVersion: 9,
    evidenceReadyCount: 800,
    evidenceValidUntil: new Date(NOW + HORIZON + 60_000).toISOString(),
    lastServerTime: new Date(NOW - 60_000).toISOString(),
    rosterCount: 800,
    rosterProjectionComplete: true,
    rosterVersion: 9,
  });
  mockedDeviceReadiness.mockResolvedValue({
    apiReachable: true,
    availableStorageBytes: 500 * 1024 * 1024,
    batteryCharging: false,
    batteryLevel: 0.8,
    databaseWritable: true,
    lowPowerMode: false,
    networkReachable: true,
  });
});

test('claims readiness only after all authoritative checks resolve green', async () => {
  const screen = await renderReadinessCard();

  await waitFor(() => expect(screen.getByText('Event readiness verified')).toBeTruthy());
  expect(screen.getByTestId('capture-gate').props.children).toBe('ready');
  expect(screen.getAllByText('PASS')).toHaveLength(15);
  expect(mockedQueueStatus).toHaveBeenCalledWith('11111111-1111-4111-8111-111111111111');
});

test('fails closed when any authoritative readiness source cannot be read', async () => {
  mockedQueueStatus.mockRejectedValueOnce(new Error('database unavailable'));
  const screen = await renderReadinessCard();

  await waitFor(() => expect(screen.getByText('Not ready for event')).toBeTruthy());
  expect(screen.getByTestId('capture-gate').props.children).toBe('blocked');
  expect(screen.getByText(
    'One or more authoritative checks could not be verified. Readiness remains blocked.',
  )).toBeTruthy();
  expect(screen.getByText('The Scan Issues queue could not be verified.')).toBeTruthy();
});

test('defines amber as capture-safe only when every required control remains green', async () => {
  mockedQueueStatus.mockResolvedValueOnce({
    awaitingConfirmation: 3,
    needsReview: 0,
    pending: 3,
    retryable: 0,
    sending: 0,
  });
  const screen = await renderReadinessCard();

  await waitFor(() => expect(screen.getByText('Attention needed before event')).toBeTruthy());
  expect(screen.getByTestId('capture-gate').props.children).toBe('attention');
  expect(screen.getByText(
    'Required controls are green. CHECK items are advisory, so offline-safe scanning remains available.',
  )).toBeTruthy();
  expect(screen.getByText('3 saved scans still need server confirmation.')).toBeTruthy();
});

test('manual refresh reruns all four authoritative readiness sources', async () => {
  const screen = await renderReadinessCard();
  await waitFor(() => expect(screen.getByText('Event readiness verified')).toBeTruthy());

  await act(async () => {
    await fireEvent.press(screen.getByText('Refresh readiness'));
    await Promise.resolve();
    await Promise.resolve();
  });
  await waitFor(() => expect(mockedReadinessEvidence).toHaveBeenCalledTimes(2));
  expect(mockedOfflineAuthorization).toHaveBeenCalledTimes(2);
  expect(mockedQueueStatus).toHaveBeenCalledTimes(2);
  expect(mockedDeviceReadiness).toHaveBeenCalledTimes(2);
});
