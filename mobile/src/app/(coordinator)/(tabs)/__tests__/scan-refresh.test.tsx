/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories load mocked host components after hoisting. */
import { act, fireEvent, render, waitFor } from '@testing-library/react-native';
import { Linking } from 'react-native';

import { recordAttendanceCameraToLocalQueue } from '@/core/observability/attendance-observability';
import {
  attendanceSessionQueueStatus,
  drainAttendanceQueue,
  enqueueQrScan,
} from '@/features/coordinator/data/attendance-queue';
import { selectAttendanceSession } from '@/features/coordinator/data/attendance-sessions';
import { useAttendanceSessions } from '@/features/coordinator/hooks/use-coordinator';
import { useCoordinatorTrips } from '@/features/coordinator/hooks/use-coordinator-trips';

import CoordinatorScanScreen from '../scan';

const mockCameraRender = jest.fn();
const mockRefreshCameraPermission = jest.fn(async () => ({ granted: true }));
const mockRequestCameraPermission = jest.fn(async () => ({ granted: true }));
const mockRequestSync = jest.fn(async (..._args: unknown[]) => ({ results: [], failures: [] }));
let mockCameraPermission = { canAskAgain: true, granted: true };

jest.mock('@/core/observability/attendance-observability', () => ({
  recordAttendanceCameraToLocalQueue: jest.fn(),
}));
jest.mock('@/core/config/env', () => ({
  env: { maestroAttendanceFixtureEnabled: true },
}));

jest.mock('expo-camera', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  const EventView = MockView as React.ComponentType<Record<string, unknown>>;
  return {
    CameraView: ({ onBarcodeScanned }: {
      onBarcodeScanned?: (result: { data: string }) => void;
    }) => {
      mockCameraRender();
      return React.createElement(EventView, { onBarcodeScanned, testID: 'attendance-camera' });
    },
    useCameraPermissions: () => [
      mockCameraPermission,
      mockRequestCameraPermission,
      mockRefreshCameraPermission,
    ],
  };
});
jest.mock('expo-haptics', () => ({
  NotificationFeedbackType: { Error: 'error', Success: 'success', Warning: 'warning' },
  notificationAsync: jest.fn(async () => undefined),
}));
jest.mock('@/features/coordinator/hooks/use-attendance-scan-feedback', () => ({
  useAttendanceScanFeedback: () => ({
    muted: false,
    preferenceBusy: false,
    preferenceError: null,
    notify: jest.fn(),
    toggleMuted: jest.fn(),
  }),
}));
jest.mock('@/features/coordinator/ui/scan-trusted-time-notice', () => ({
  ScanTrustedTimeNotice: () => null,
}));
jest.mock('@/features/coordinator/ui/scan-feedback-audio-toggle', () => ({
  ScanFeedbackAudioToggle: () => null,
}));
jest.mock('@/core/realtime/realtime-status', () => ({
  useRealtimeStatusStore: (
    selector: (state: { status: 'reconnecting' }) => unknown,
  ) => selector({ status: 'reconnecting' }),
}));
jest.mock('@/core/sync/sync-trigger', () => ({
  requestSync: (...args: unknown[]) => mockRequestSync(...args),
}));
jest.mock('lucide-react-native/icons/circle-check-big', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(MockView) };
});
jest.mock('lucide-react-native/icons/flashlight', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(MockView) };
});
jest.mock('lucide-react-native/icons/flashlight-off', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(MockView) };
});
jest.mock('lucide-react-native/icons/scan-line', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(MockView) };
});
jest.mock('lucide-react-native/icons/triangle-alert', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(MockView) };
});
jest.mock('@/features/coordinator/data/attendance-queue', () => ({
  attendanceSessionQueueStatus: jest.fn(async () => ({
    pending: 0,
    sending: 0,
    retryable: 0,
    needsReview: 0,
    awaitingConfirmation: 0,
  })),
  drainAttendanceQueue: jest.fn(async () => ({
    settledBySession: {},
    confirmedBySession: {},
    newlyAcceptedBySession: {},
    rejectedBySession: {},
  })),
  enqueueQrScan: jest.fn(),
}));
jest.mock('@/features/coordinator/data/attendance-sessions', () => ({
  selectAttendanceSession: jest.fn(async () => undefined),
}));
jest.mock('@/features/coordinator/hooks/use-coordinator', () => ({
  useAttendanceSessions: jest.fn(),
}));
jest.mock('@/features/coordinator/hooks/use-coordinator-trips', () => ({
  useCoordinatorTrips: jest.fn(),
}));
jest.mock('@/design/components/content-state', () => {
  const React = require('react') as typeof import('react');
  const { Text: MockText } = require('react-native') as typeof import('react-native');
  const State = ({ label, message }: { label?: string; message?: string }) => (
    React.createElement(MockText, null, label ?? message ?? '')
  );
  return { ContentEmpty: State, ContentError: State, ContentLoading: State };
});
jest.mock('@/design/components/page-header', () => {
  const React = require('react') as typeof import('react');
  const { Text: MockText } = require('react-native') as typeof import('react-native');
  return {
    PageHeader: ({ title }: { title: string }) => React.createElement(MockText, null, title),
  };
});
jest.mock('@/design/components/screen', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  const EventView = MockView as React.ComponentType<Record<string, unknown>>;
  return {
    Screen: ({ children, scrollProps }: {
      children: React.ReactNode;
      scrollProps?: { refreshControl?: React.ReactElement<{ onRefresh?: () => void; testID?: string }> };
    }) => React.createElement(
      MockView,
      null,
      scrollProps?.refreshControl
        ? React.createElement(EventView, {
          onRefresh: scrollProps.refreshControl.props.onRefresh,
          testID: scrollProps.refreshControl.props.testID,
        })
        : null,
      children,
    ),
  };
});

const mockedSelectSession = jest.mocked(selectAttendanceSession);
const mockedCameraToLocalQueue = jest.mocked(recordAttendanceCameraToLocalQueue);
const mockedQueueStatus = jest.mocked(attendanceSessionQueueStatus);
const mockedDrainQueue = jest.mocked(drainAttendanceQueue);
const mockedEnqueueScan = jest.mocked(enqueueQrScan);
const mockedUseAttendanceSessions = jest.mocked(useAttendanceSessions);
const mockedUseCoordinatorTrips = jest.mocked(useCoordinatorTrips);

const ACTIVE_SESSION = {
  id: '22222222-2222-4222-8222-222222222222',
  name: 'Airport reporting',
  status: 'active' as const,
  scanned_count: 20,
  assigned_count: 100,
  started_at: '2029-01-01T00:00:00.000Z',
  completed_at: null,
};
const VALID_ATTENDANCE_QR = `pdatt:${'A'.repeat(43)}`;

beforeEach(() => {
  jest.clearAllMocks();
  mockCameraPermission = { canAskAgain: true, granted: true };
  mockedQueueStatus.mockResolvedValue({
    pending: 0,
    sending: 0,
    retryable: 0,
    needsReview: 0,
    awaitingConfirmation: 0,
  });
  mockedDrainQueue.mockResolvedValue({
    settledBySession: {},
    confirmedBySession: {},
    newlyAcceptedBySession: {},
    rejectedBySession: {},
  });
  mockedEnqueueScan.mockResolvedValue({
    status: 'queued',
    idempotencyKey: '33333333-3333-4333-8333-333333333333',
    duplicate: false,
  });
  mockedUseCoordinatorTrips.mockReturnValue({
    selectedTripId: '11111111-1111-4111-8111-111111111111',
    selectedTrip: { name: 'Enterprise Group' },
  } as ReturnType<typeof useCoordinatorTrips>);
  mockRequestSync.mockResolvedValue({ results: [], failures: [] });
});

afterEach(() => {
  jest.restoreAllMocks();
});

test('requests camera permission and opens the scanner immediately after access is granted', async () => {
  const refetch = jest.fn(async () => ({ data: { items: [ACTIVE_SESSION] } }));
  mockedUseAttendanceSessions.mockReturnValue({
    data: { items: [ACTIVE_SESSION], selectedSessionId: ACTIVE_SESSION.id },
    isPending: false,
    isError: false,
    refetch,
  } as unknown as ReturnType<typeof useAttendanceSessions>);
  mockCameraPermission = { canAskAgain: true, granted: false };

  const screen = await render(<CoordinatorScanScreen />);
  expect(screen.getByText('Camera access is needed')).toBeTruthy();
  expect(screen.queryByTestId('attendance-camera')).toBeNull();
  expect(screen.queryByText('Not ready for event')).toBeNull();
  expect(screen.queryByText('Scanner locked by Event Ready')).toBeNull();
  await fireEvent.press(screen.getByText('Allow camera'));
  expect(mockRequestCameraPermission).toHaveBeenCalledTimes(1);

  mockCameraPermission = { canAskAgain: true, granted: true };
  await screen.rerender(<CoordinatorScanScreen />);
  expect(screen.getByTestId('attendance-camera')).toBeTruthy();
  expect(screen.queryByText('Camera access is needed')).toBeNull();
  expect(screen.queryByText('Not ready for event')).toBeNull();
});

test('opens app settings instead of retrying a permanently denied camera permission', async () => {
  mockedUseAttendanceSessions.mockReturnValue({
    data: { items: [ACTIVE_SESSION], selectedSessionId: ACTIVE_SESSION.id },
    isPending: false,
    isError: false,
    refetch: jest.fn(async () => ({ data: { items: [ACTIVE_SESSION] } })),
  } as unknown as ReturnType<typeof useAttendanceSessions>);
  mockCameraPermission = { canAskAgain: false, granted: false };
  const openSettings = jest.spyOn(Linking, 'openSettings').mockResolvedValue();

  const screen = await render(<CoordinatorScanScreen />);
  expect(screen.getByText('Enable Camera in your phone settings to scan attendance QR codes.')).toBeTruthy();
  expect(screen.queryByText('Allow camera')).toBeNull();
  await fireEvent.press(screen.getByText('Open app settings'));

  expect(openSettings).toHaveBeenCalledTimes(1);
  expect(mockRequestCameraPermission).not.toHaveBeenCalled();
});

test('rejects a stale camera callback after camera permission is revoked', async () => {
  const refetch = jest.fn(async () => ({ data: { items: [ACTIVE_SESSION] } }));
  mockedUseAttendanceSessions.mockReturnValue({
    data: { items: [ACTIVE_SESSION], selectedSessionId: ACTIVE_SESSION.id },
    isPending: false,
    isError: false,
    refetch,
  } as unknown as ReturnType<typeof useAttendanceSessions>);
  const screen = await render(<CoordinatorScanScreen />);
  const staleCallback = screen.getByTestId('attendance-camera').props.onBarcodeScanned as (
    result: { data: string }
  ) => Promise<void>;

  mockCameraPermission = { canAskAgain: true, granted: false };
  await screen.rerender(<CoordinatorScanScreen />);
  expect(screen.queryByTestId('attendance-camera')).toBeNull();
  await act(async () => {
    await staleCallback({ data: VALID_ATTENDANCE_QR });
  });
  expect(mockedEnqueueScan).not.toHaveBeenCalled();
  expect(mockedCameraToLocalQueue).not.toHaveBeenCalled();
});

test('routes a permitted camera scan through the secure attendance queue', async () => {
  mockedUseAttendanceSessions.mockReturnValue({
    data: { items: [ACTIVE_SESSION], selectedSessionId: ACTIVE_SESSION.id },
    isPending: false,
    isError: false,
    refetch: jest.fn(async () => ({ data: { items: [ACTIVE_SESSION] } })),
  } as unknown as ReturnType<typeof useAttendanceSessions>);
  const screen = await render(<CoordinatorScanScreen />);
  await fireEvent(
    screen.getByTestId('attendance-camera'),
    'barcodeScanned',
    { data: VALID_ATTENDANCE_QR },
  );

  await waitFor(() => expect(mockedEnqueueScan).toHaveBeenCalledWith(
    '11111111-1111-4111-8111-111111111111',
    ACTIVE_SESSION.id,
    VALID_ATTENDANCE_QR,
    { assignedCount: 100 },
  ));
});

test('routes protected preview fixture input through the real secure scan handler', async () => {
  mockedUseAttendanceSessions.mockReturnValue({
    data: { items: [ACTIVE_SESSION], selectedSessionId: ACTIVE_SESSION.id },
    isPending: false,
    isError: false,
    refetch: jest.fn(async () => ({ data: { items: [ACTIVE_SESSION] } })),
  } as unknown as ReturnType<typeof useAttendanceSessions>);

  const screen = await render(<CoordinatorScanScreen />);
  expect(screen.getByTestId('attendance-e2e-fixture')).toBeTruthy();
  await act(async () => {
    await fireEvent.changeText(screen.getByTestId('attendance-e2e-qr-input'), VALID_ATTENDANCE_QR);
  });
  expect(screen.getByTestId('attendance-e2e-submit').props.accessibilityState).toMatchObject({
    disabled: false,
  });
  await act(async () => {
    await fireEvent.press(screen.getByTestId('attendance-e2e-submit'));
  });

  await waitFor(() => expect(mockedEnqueueScan).toHaveBeenCalledWith(
    '11111111-1111-4111-8111-111111111111',
    ACTIVE_SESSION.id,
    VALID_ATTENDANCE_QR,
    { assignedCount: 100 },
  ));
  expect(screen.getByTestId('attendance-e2e-qr-input').props.value).toBe('');
});

test('shows degraded realtime state and offers authoritative manual synchronization', async () => {
  const refetch = jest.fn(async () => ({ data: { items: [ACTIVE_SESSION] } }));
  mockedUseAttendanceSessions.mockReturnValue({
    data: { items: [ACTIVE_SESSION], selectedSessionId: ACTIVE_SESSION.id },
    isPending: false,
    isError: false,
    refetch,
  } as unknown as ReturnType<typeof useAttendanceSessions>);
  const screen = await render(<CoordinatorScanScreen />);

  expect(screen.getByText('Live updates delayed')).toBeTruthy();
  await fireEvent.press(screen.getByTestId('scan-manual-sync'));

  await waitFor(() => expect(mockRequestSync).toHaveBeenCalledWith({
    scope: 'trip',
    tripId: '11111111-1111-4111-8111-111111111111',
    reason: 'manual-realtime-degraded',
  }));
  expect(refetch).toHaveBeenCalled();
});

test('refreshes only the activity manager and preserves the selected activity and live count', async () => {
  const refetch = jest.fn(async () => undefined);
  mockedUseAttendanceSessions.mockReturnValue({
    data: {
      items: [ACTIVE_SESSION],
      selectedSessionId: ACTIVE_SESSION.id,
    },
    isPending: false,
    isError: false,
    refetch,
  } as unknown as ReturnType<typeof useAttendanceSessions>);

  const screen = await render(<CoordinatorScanScreen />);
  expect(screen.getByTestId('attendance-camera')).toBeTruthy();
  expect(screen.queryByTestId('scan-activity-list')).toBeNull();
  expect(screen.getByText('20 of 100 scanned')).toBeTruthy();
  expect(mockCameraRender).toHaveBeenCalledTimes(1);

  await fireEvent.press(screen.getByText('Change'));
  expect(screen.queryByTestId('attendance-camera')).toBeNull();
  expect(screen.getByText('Select a prepared activity')).toBeTruthy();
  expect(screen.queryByText('Create an activity')).toBeNull();
  expect(screen.queryByText('Create and start scanning')).toBeNull();
  await fireEvent(screen.getByTestId('scan-activity-list'), 'refresh');

  expect(refetch).toHaveBeenCalledTimes(1);
  expect(screen.getByText('Airport reporting')).toBeTruthy();
  expect(screen.getByText('20 of 100 scanned')).toBeTruthy();
  expect(mockCameraRender).toHaveBeenCalledTimes(1);

  await fireEvent.press(screen.getByLabelText('Continue Airport reporting'));
  await waitFor(() => expect(mockedSelectSession).toHaveBeenCalledWith(
    '11111111-1111-4111-8111-111111111111',
    ACTIVE_SESSION.id,
  ));
  await waitFor(() => expect(screen.getByTestId('attendance-camera')).toBeTruthy());
  expect(screen.getByText('20 of 100 scanned')).toBeTruthy();
});

test('shows durable pending feedback and only says checked in after server acknowledgement', async () => {
  const refetch = jest.fn(async () => ({
    data: { items: [ACTIVE_SESSION] },
  }));
  mockedUseAttendanceSessions.mockReturnValue({
    data: {
      items: [ACTIVE_SESSION],
      selectedSessionId: ACTIVE_SESSION.id,
    },
    isPending: false,
    isError: false,
    refetch,
  } as unknown as ReturnType<typeof useAttendanceSessions>);
  let resolveDrain!: (value: Awaited<ReturnType<typeof drainAttendanceQueue>>) => void;
  mockedDrainQueue.mockImplementationOnce(() => new Promise((resolve) => {
    resolveDrain = resolve;
  }));

  const screen = await render(<CoordinatorScanScreen />);
  await fireEvent(
    screen.getByTestId('attendance-camera'),
    'barcodeScanned',
    { data: VALID_ATTENDANCE_QR },
  );

  await waitFor(() => expect(mockedEnqueueScan).toHaveBeenCalledWith(
    '11111111-1111-4111-8111-111111111111',
    ACTIVE_SESSION.id,
    VALID_ATTENDANCE_QR,
    { assignedCount: 100 },
  ));
  expect(screen.getByText('Saved — confirmation pending')).toBeTruthy();
  expect(mockedCameraToLocalQueue).toHaveBeenCalledWith(expect.any(Number), 'queued');
  expect(screen.getByText('1 saved on this device — awaiting server confirmation')).toBeTruthy();
  expect(screen.getByText('20 of 100 scanned')).toBeTruthy();
  expect(screen.queryByText('Checked in')).toBeNull();

  await waitFor(() => expect(mockedDrainQueue).toHaveBeenCalledTimes(1));
  resolveDrain({
    settledBySession: { [ACTIVE_SESSION.id]: 1 },
    confirmedBySession: { [ACTIVE_SESSION.id]: 1 },
    newlyAcceptedBySession: { [ACTIVE_SESSION.id]: 1 },
    rejectedBySession: {},
  });

  await waitFor(() => expect(screen.getByText('Checked in')).toBeTruthy());
  expect(screen.getByText('21 of 100 scanned')).toBeTruthy();
  expect(screen.queryByText('1 saved on this device — awaiting server confirmation')).toBeNull();
});

test('stops safely with an actionable message when the durable queue reaches capacity', async () => {
  const refetch = jest.fn(async () => undefined);
  mockedUseAttendanceSessions.mockReturnValue({
    data: {
      items: [ACTIVE_SESSION],
      selectedSessionId: ACTIVE_SESSION.id,
    },
    isPending: false,
    isError: false,
    refetch,
  } as unknown as ReturnType<typeof useAttendanceSessions>);
  mockedEnqueueScan.mockResolvedValueOnce({
    status: 'capacity_reached',
    capacity: 'session',
    idempotencyKey: null,
    duplicate: false,
  });

  const screen = await render(<CoordinatorScanScreen />);
  await fireEvent(
    screen.getByTestId('attendance-camera'),
    'barcodeScanned',
    { data: VALID_ATTENDANCE_QR },
  );

  await waitFor(() => expect(
    screen.getByText('Unsent scan limit reached — connect and sync before scanning more'),
  ).toBeTruthy());
  expect(screen.queryByText('Saved — confirmation pending')).toBeNull();
  expect(screen.queryByText(/saved on this device/)).toBeNull();
  expect(screen.getByText('20 of 100 scanned')).toBeTruthy();
  expect(mockedCameraToLocalQueue).toHaveBeenCalledWith(
    expect.any(Number),
    'capacity_reached',
  );
});

test('records a queue-boundary failure without exposing the scanned QR', async () => {
  mockedUseAttendanceSessions.mockReturnValue({
    data: { items: [ACTIVE_SESSION], selectedSessionId: ACTIVE_SESSION.id },
    isPending: false,
    isError: false,
    refetch: jest.fn(async () => undefined),
  } as unknown as ReturnType<typeof useAttendanceSessions>);
  mockedEnqueueScan.mockRejectedValueOnce(new Error('database unavailable'));

  const screen = await render(<CoordinatorScanScreen />);
  await fireEvent(
    screen.getByTestId('attendance-camera'),
    'barcodeScanned',
    { data: VALID_ATTENDANCE_QR },
  );

  await waitFor(() => expect(mockedCameraToLocalQueue).toHaveBeenCalledWith(
    expect.any(Number),
    'failure',
  ));
  expect(JSON.stringify(mockedCameraToLocalQueue.mock.calls)).not.toContain(VALID_ATTENDANCE_QR);
});
