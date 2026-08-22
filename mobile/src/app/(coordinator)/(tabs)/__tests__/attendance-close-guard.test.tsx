/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories load mocked host components after hoisting. */
import { act, fireEvent, render, waitFor } from '@testing-library/react-native';
import { Alert } from 'react-native';

import { leaveAttendanceSession } from '@/features/coordinator/data/attendance-sessions';
import { useAttendanceSessions } from '@/features/coordinator/hooks/use-coordinator';
import { useCoordinatorTrips } from '@/features/coordinator/hooks/use-coordinator-trips';

import CoordinatorAttendanceScreen from '../attendance';

jest.mock('expo-router', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@/core/query/use-route-focus', () => ({ useRouteFocus: () => true }));
jest.mock('lucide-react-native/icons/triangle-alert', () => {
  const React = require('react') as typeof import('react');
  const { View } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(View) };
});
jest.mock('lucide-react-native/icons/circle-check-big', () => {
  const React = require('react') as typeof import('react');
  const { View } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(View) };
});
jest.mock('lucide-react-native/icons/chevron-right', () => {
  const React = require('react') as typeof import('react');
  const { View } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(View) };
});
jest.mock('lucide-react-native/icons/clock-3', () => {
  const React = require('react') as typeof import('react');
  const { View } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(View) };
});
jest.mock('@/core/query/use-manual-refresh', () => ({
  useManualRefresh: () => ({ isRefreshing: false, refresh: (task: () => Promise<unknown>) => task() }),
}));
jest.mock('@/features/coordinator/data/attendance-sessions', () => ({
  leaveAttendanceSession: jest.fn(async () => undefined),
  selectAttendanceSession: jest.fn(async () => undefined),
}));
jest.mock('@/features/coordinator/hooks/use-coordinator', () => ({
  useAttendanceSessions: jest.fn(),
  useCoordinatorAttendanceRoster: () => ({
    data: undefined,
    isPending: false,
    isError: false,
    refetch: jest.fn(async () => undefined),
  }),
}));
jest.mock('@/features/coordinator/hooks/use-coordinator-trips', () => ({
  useCoordinatorTrips: jest.fn(),
}));
jest.mock('@/design/components/content-state', () => {
  const React = require('react') as typeof import('react');
  const { Text } = require('react-native') as typeof import('react-native');
  const State = ({ label, message, title }: { label?: string; message?: string; title?: string }) => (
    React.createElement(Text, null, label ?? message ?? title ?? '')
  );
  return { ContentEmpty: State, ContentError: State, ContentLoading: State };
});
jest.mock('@/design/components/glass-card', () => {
  const React = require('react') as typeof import('react');
  const { View } = require('react-native') as typeof import('react-native');
  return { GlassCard: ({ children }: { children: React.ReactNode }) => React.createElement(View, null, children) };
});
jest.mock('@/design/components/page-header', () => {
  const React = require('react') as typeof import('react');
  const { Text } = require('react-native') as typeof import('react-native');
  return { PageHeader: ({ title }: { title: string }) => React.createElement(Text, null, title) };
});
jest.mock('@/design/components/primary-button', () => {
  const React = require('react') as typeof import('react');
  const { Pressable, Text } = require('react-native') as typeof import('react-native');
  return {
    PrimaryButton: ({ label, onPress }: { label: string; onPress: () => void }) => (
      React.createElement(Pressable, { accessibilityRole: 'button', onPress }, React.createElement(Text, null, label))
    ),
  };
});
jest.mock('@/design/components/screen', () => {
  const React = require('react') as typeof import('react');
  const { View } = require('react-native') as typeof import('react-native');
  return { Screen: ({ children }: { children: React.ReactNode }) => React.createElement(View, null, children) };
});
jest.mock('@/design/components/status-pill', () => {
  const React = require('react') as typeof import('react');
  const { Text } = require('react-native') as typeof import('react-native');
  return { StatusPill: ({ label }: { label: string }) => React.createElement(Text, null, label) };
});
jest.mock('@/features/coordinator/ui/attendance-activity-summary', () => {
  const React = require('react') as typeof import('react');
  const { Text } = require('react-native') as typeof import('react-native');
  return {
    AttendanceActivitySummary: ({ session }: { session: { name: string } }) => (
      React.createElement(Text, null, `Summary ${session.name}`)
    ),
  };
});

const mockedLeave = jest.mocked(leaveAttendanceSession);
const mockedSessions = jest.mocked(useAttendanceSessions);
const mockedTrips = jest.mocked(useCoordinatorTrips);
const tripId = '11111111-1111-4111-8111-111111111111';
const activeSession = {
  id: '22222222-2222-4222-8222-222222222222',
  name: 'Airport reporting',
  status: 'active' as const,
  scanned_count: 794,
  assigned_count: 800,
  started_at: '2030-01-01T00:00:00.000Z',
  completed_at: null,
};

beforeEach(() => {
  jest.clearAllMocks();
  mockedTrips.mockReturnValue({
    selectedTripId: tripId,
    selectedTrip: { name: 'Enterprise Group' },
  } as ReturnType<typeof useCoordinatorTrips>);
});

afterEach(() => {
  jest.restoreAllMocks();
});

test('coordinator can only finish locally and never sees a global close control', async () => {
  const refetch = jest.fn().mockResolvedValue({
    data: { items: [activeSession], selectedSessionId: null },
    error: null,
  });
  mockedSessions.mockReturnValue({
    data: { items: [activeSession], selectedSessionId: activeSession.id },
    isPending: false,
    isError: false,
    refetch,
  } as unknown as ReturnType<typeof useAttendanceSessions>);
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  const screen = await render(<CoordinatorAttendanceScreen />);

  expect(screen.queryByText(/complete selected activity/i)).toBeNull();
  await fireEvent.press(screen.getByText('Finish my scanning'));

  expect(alert).toHaveBeenCalledTimes(1);
  expect(alert.mock.calls[0]?.[1]).toContain('only leaves the activity on your device');
  const buttons = alert.mock.calls[0]?.[2];
  await act(async () => {
    buttons?.find((button) => button.text === 'Finish my scanning')?.onPress?.();
    await Promise.resolve();
  });

  await waitFor(() => expect(mockedLeave).toHaveBeenCalledWith(tripId, activeSession.id));
  await waitFor(() => expect(refetch).toHaveBeenCalledTimes(1));
});

test('reports a successful local leave separately when only the list refresh fails', async () => {
  const refetch = jest.fn().mockResolvedValue({
    data: undefined,
    error: new Error('refresh unavailable'),
  });
  mockedSessions.mockReturnValue({
    data: { items: [activeSession], selectedSessionId: activeSession.id },
    isPending: false,
    isError: false,
    refetch,
  } as unknown as ReturnType<typeof useAttendanceSessions>);
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  const screen = await render(<CoordinatorAttendanceScreen />);

  await fireEvent.press(screen.getByText('Finish my scanning'));
  await act(async () => {
    alert.mock.calls[0]?.[2]?.find((button) => button.text === 'Finish my scanning')?.onPress?.();
    await Promise.resolve();
  });

  await waitFor(() => expect(mockedLeave).toHaveBeenCalledWith(tripId, activeSession.id));
  await waitFor(() => expect(screen.getByText(
    'This device left the activity, but the latest activity list could not be loaded.',
  )).toBeTruthy());
  expect(screen.queryByText('This device could not leave the activity.')).toBeNull();
});
