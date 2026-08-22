/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories load mocked host components after hoisting. */
import { act, fireEvent, render, waitFor } from '@testing-library/react-native';
import { Alert } from 'react-native';

import {
  completeManagerAttendanceSession,
  createManagerAttendanceSession,
  loadManagerAttendanceCloseoutStatus,
  type AttendanceCloseoutStatus,
} from '@/features/manager/data/manager-operations';
import {
  useManagerAttendanceRoster,
  useManagerAttendanceSessions,
} from '@/features/manager/hooks/use-manager-operations';
import { useTrips } from '@/features/trips/hooks/use-trips';

import ManagerAttendanceScreen from '../attendance';

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
jest.mock('@/features/manager/data/manager-operations', () => ({
  completeManagerAttendanceSession: jest.fn(async () => undefined),
  createManagerAttendanceSession: jest.fn(async () => undefined),
  loadManagerAttendanceCloseoutStatus: jest.fn(),
}));
jest.mock('@/features/manager/hooks/use-manager-operations', () => ({
  useManagerAttendanceRoster: jest.fn(),
  useManagerAttendanceSessions: jest.fn(),
}));
jest.mock('@/features/trips/hooks/use-trips', () => ({ useTrips: jest.fn() }));
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
jest.mock('@/design/components/primary-button', () => {
  const React = require('react') as typeof import('react');
  const { Pressable, Text } = require('react-native') as typeof import('react-native');
  return {
    PrimaryButton: ({ disabled, label, onPress }: { disabled?: boolean; label: string; onPress: () => void }) => (
      React.createElement(Pressable, { accessibilityRole: 'button', disabled, onPress }, React.createElement(Text, null, label))
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
jest.mock('@/design/components/text-field', () => {
  const React = require('react') as typeof import('react');
  const { TextInput } = require('react-native') as typeof import('react-native');
  return {
    TextField: ({ label, ...props }: { label: string }) => (
      React.createElement(TextInput, { accessibilityLabel: label, ...props })
    ),
  };
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
jest.mock('@/features/coordinator/ui/operation-header', () => {
  const React = require('react') as typeof import('react');
  const { Text } = require('react-native') as typeof import('react-native');
  return { OperationHeader: ({ title }: { title: string }) => React.createElement(Text, null, title) };
});

const mockedComplete = jest.mocked(completeManagerAttendanceSession);
const mockedCreate = jest.mocked(createManagerAttendanceSession);
const mockedLoadCloseout = jest.mocked(loadManagerAttendanceCloseoutStatus);
const mockedRoster = jest.mocked(useManagerAttendanceRoster);
const mockedSessions = jest.mocked(useManagerAttendanceSessions);
const mockedTrips = jest.mocked(useTrips);
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
const readyCloseout: AttendanceCloseoutStatus = {
  ready: true,
  checkpoint_ttl_seconds: 120,
  active_assignment_count: 1,
  ready_assignment_count: 1,
  missing_assignment_count: 0,
  stale_assignment_count: 0,
  nonzero_assignment_count: 0,
  blocked_assignment_count: 0,
  unresolved_count: 0,
  oldest_pending_age_seconds: null,
  coordinators: [{
    coordinator_id: '77777777-7777-4777-8777-777777777777',
    coordinator_name: 'Coordinator One',
    state: 'ready' as const,
    reported_at: '2030-01-01T00:00:00.000Z',
    report_age_seconds: 0,
    pending_count: 0,
    sending_count: 0,
    retryable_count: 0,
    needs_review_count: 0,
    unreviewed_rejected_count: 0,
    oldest_pending_age_seconds: null,
  }],
};

beforeEach(() => {
  jest.clearAllMocks();
  mockedLoadCloseout.mockResolvedValue(readyCloseout);
  mockedTrips.mockReturnValue({
    selectedTripId: tripId,
    selectedTrip: { name: 'Enterprise Group' },
  } as ReturnType<typeof useTrips>);
  mockedRoster.mockReturnValue({
    data: undefined,
    isPending: false,
    isError: false,
    isRefetching: false,
    refetch: jest.fn(async () => undefined),
  } as unknown as ReturnType<typeof useManagerAttendanceRoster>);
});

afterEach(() => {
  jest.restoreAllMocks();
});

test('manager prepares a canonical activity and refreshes the selectable list', async () => {
  const created = {
    ...activeSession,
    id: '33333333-3333-4333-8333-333333333333',
    name: 'Hotel departure count',
    scanned_count: 0,
  };
  const refetch = jest.fn().mockResolvedValue({ data: { items: [created] }, error: null });
  mockedCreate.mockResolvedValueOnce(created);
  mockedSessions.mockReturnValue({
    data: { items: [] },
    isPending: false,
    isError: false,
    isRefetching: false,
    refetch,
  } as unknown as ReturnType<typeof useManagerAttendanceSessions>);
  const screen = await render(<ManagerAttendanceScreen />);

  await fireEvent.changeText(screen.getByLabelText('Activity name'), '  Hotel departure count  ');
  await fireEvent.press(screen.getByText('Create activity'));

  await waitFor(() => expect(mockedCreate).toHaveBeenCalledWith(tripId, 'Hotel departure count'));
  await waitFor(() => expect(refetch).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByText(
    'Hotel departure count is ready for coordinators to select.',
  )).toBeTruthy());
});

test('manager sees authoritative coordinator checkpoints before a normal close', async () => {
  const authoritativeSession = { ...activeSession, scanned_count: 799 };
  const refetch = jest.fn()
    .mockResolvedValueOnce({ data: { items: [authoritativeSession] }, error: null })
    .mockResolvedValueOnce({
      data: { items: [{ ...authoritativeSession, status: 'completed' as const }] },
      error: null,
    });
  mockedSessions.mockReturnValue({
    data: { items: [activeSession] },
    isPending: false,
    isError: false,
    isRefetching: false,
    refetch,
  } as unknown as ReturnType<typeof useManagerAttendanceSessions>);
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  const screen = await render(<ManagerAttendanceScreen />);

  await fireEvent.press(screen.getByLabelText('Airport reporting, 794 of 800 counted'));
  await waitFor(() => expect(screen.getByText(/1 of 1 assigned coordinator accounts/)).toBeTruthy());
  await fireEvent.press(screen.getByText('Close after clear checkpoints'));

  await waitFor(() => expect(alert).toHaveBeenCalledTimes(1));
  expect(alert.mock.calls[0]?.[1]).toContain('server confirms 799 of 800');
  expect(alert.mock.calls[0]?.[1]).toContain('assigned coordinator accounts recently reported clear');
  await act(async () => {
    alert.mock.calls[0]?.[2]?.find((button) => button.text === 'Continue')?.onPress?.();
  });

  expect(alert).toHaveBeenCalledTimes(2);
  expect(alert.mock.calls[1]?.[1]).toContain('does not discard scans already saved before closure');
  await act(async () => {
    alert.mock.calls[1]?.[2]?.find((button) => button.text === 'Close activity')?.onPress?.();
    await Promise.resolve();
  });

  await waitFor(() => expect(mockedComplete).toHaveBeenCalledWith(
    tripId,
    activeSession.id,
    undefined,
  ));
  await waitFor(() => expect(refetch).toHaveBeenCalledTimes(2));
});

test('reports a successful close separately when only the follow-up refresh fails', async () => {
  const refetch = jest.fn()
    .mockResolvedValueOnce({ data: { items: [activeSession] }, error: null })
    .mockResolvedValueOnce({ data: undefined, error: new Error('refresh unavailable') });
  mockedSessions.mockReturnValue({
    data: { items: [activeSession] },
    isPending: false,
    isError: false,
    isRefetching: false,
    refetch,
  } as unknown as ReturnType<typeof useManagerAttendanceSessions>);
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  const screen = await render(<ManagerAttendanceScreen />);

  await fireEvent.press(screen.getByLabelText('Airport reporting, 794 of 800 counted'));
  await waitFor(() => expect(screen.getByText('Close after clear checkpoints')).toBeTruthy());
  await fireEvent.press(screen.getByText('Close after clear checkpoints'));
  await waitFor(() => expect(alert).toHaveBeenCalledTimes(1));
  await act(async () => {
    alert.mock.calls[0]?.[2]?.find((button) => button.text === 'Continue')?.onPress?.();
    alert.mock.calls[1]?.[2]?.find((button) => button.text === 'Close activity')?.onPress?.();
    await Promise.resolve();
  });

  await waitFor(() => expect(mockedComplete).toHaveBeenCalledWith(
    tripId,
    activeSession.id,
    undefined,
  ));
  await waitFor(() => expect(screen.getByText(
    'The shared activity was closed, but the latest status could not be loaded.',
  )).toBeTruthy());
  expect(screen.queryByText('The shared activity could not be closed.')).toBeNull();
});

test('blocked checkpoints require a privacy-safe reason and two-step audited override', async () => {
  const blockedCloseout = {
    ...readyCloseout,
    ready: false,
    ready_assignment_count: 0,
    nonzero_assignment_count: 1,
    blocked_assignment_count: 1,
    unresolved_count: 2,
    oldest_pending_age_seconds: 35,
    coordinators: [{
      ...readyCloseout.coordinators[0]!,
      state: 'blocked' as const,
      pending_count: 2,
      oldest_pending_age_seconds: 35,
    }],
  };
  mockedLoadCloseout.mockResolvedValue(blockedCloseout);
  const refetch = jest.fn()
    .mockResolvedValueOnce({ data: { items: [activeSession] }, error: null })
    .mockResolvedValueOnce({
      data: { items: [{ ...activeSession, status: 'completed' as const }] },
      error: null,
    });
  mockedSessions.mockReturnValue({
    data: { items: [activeSession] },
    isPending: false,
    isError: false,
    isRefetching: false,
    refetch,
  } as unknown as ReturnType<typeof useManagerAttendanceSessions>);
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  const screen = await render(<ManagerAttendanceScreen />);

  await fireEvent.press(screen.getByLabelText('Airport reporting, 794 of 800 counted'));
  await waitFor(() => expect(screen.getByText(/1 of 1 coordinator checkpoints are missing/)).toBeTruthy());
  expect(screen.getByText(/Do not enter passenger names/)).toBeTruthy();
  await fireEvent.changeText(
    screen.getByLabelText('Operational exception reason'),
    'approved transport emergency override',
  );
  await fireEvent.press(screen.getByText('Override checkpoint guard and close'));

  await waitFor(() => expect(alert).toHaveBeenCalledTimes(1));
  expect(alert.mock.calls[0]?.[0]).toBe('Review audited manager exception');
  expect(alert.mock.calls[0]?.[1]).toContain('2 unresolved items');
  await act(async () => {
    alert.mock.calls[0]?.[2]?.find((button) => button.text === 'Continue')?.onPress?.();
  });
  expect(alert.mock.calls[1]?.[0]).toBe('Override the closeout guard?');
  await act(async () => {
    alert.mock.calls[1]?.[2]?.find((button) => button.text === 'Override and close')?.onPress?.();
    await Promise.resolve();
  });

  await waitFor(() => expect(mockedComplete).toHaveBeenCalledWith(
    tripId,
    activeSession.id,
    'approved transport emergency override',
  ));
});

test('manager close remains disabled when coordinator checkpoint status is unavailable', async () => {
  mockedLoadCloseout.mockRejectedValue(new Error('status unavailable'));
  mockedSessions.mockReturnValue({
    data: { items: [activeSession] },
    isPending: false,
    isError: false,
    isRefetching: false,
    refetch: jest.fn(),
  } as unknown as ReturnType<typeof useManagerAttendanceSessions>);
  const screen = await render(<ManagerAttendanceScreen />);

  await fireEvent.press(screen.getByLabelText('Airport reporting, 794 of 800 counted'));
  await waitFor(() => expect(screen.getByText(
    'Coordinator checkpoint evidence is unavailable. Closeout is disabled until it can be refreshed.',
  )).toBeTruthy());
  const closeButton = screen.getByText('Override checkpoint guard and close').parent;
  expect(closeButton?.props.accessibilityState?.disabled ?? closeButton?.props.disabled).toBe(true);
  expect(mockedComplete).not.toHaveBeenCalled();
});

test('fails closed when authoritative pre-close evidence cannot be refreshed', async () => {
  const refetch = jest.fn().mockRejectedValue(new Error('refresh unavailable'));
  mockedSessions.mockReturnValue({
    data: { items: [activeSession] },
    isPending: false,
    isError: false,
    isRefetching: false,
    refetch,
  } as unknown as ReturnType<typeof useManagerAttendanceSessions>);
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  const screen = await render(<ManagerAttendanceScreen />);

  await fireEvent.press(screen.getByLabelText('Airport reporting, 794 of 800 counted'));
  await waitFor(() => expect(screen.getByText('Close after clear checkpoints')).toBeTruthy());
  await fireEvent.press(screen.getByText('Close after clear checkpoints'));

  await waitFor(() => expect(screen.getByText(
    'The authoritative coordinator closeout evidence could not be refreshed, so the activity was not closed.',
  )).toBeTruthy());
  expect(alert).not.toHaveBeenCalled();
  expect(mockedComplete).not.toHaveBeenCalled();
});
