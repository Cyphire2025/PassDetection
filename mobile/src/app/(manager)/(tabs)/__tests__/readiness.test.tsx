/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories load host components after hoisting. */
import { fireEvent, render } from '@testing-library/react-native';

import ManagerReadinessScreen from '../readiness';

const mockPush = jest.fn();
const mockReadiness = jest.fn();
const mockAttendance = jest.fn();
const mockTrips = jest.fn();

jest.mock('expo-router', () => ({ useRouter: () => ({ push: mockPush }) }));
jest.mock('lucide-react-native/icons/clipboard-check', () => {
  const React = require('react') as typeof import('react');
  const { View } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(View) };
});
jest.mock('lucide-react-native/icons/file-check', () => {
  const React = require('react') as typeof import('react');
  const { View } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(View) };
});
jest.mock('lucide-react-native/icons/plane', () => {
  const React = require('react') as typeof import('react');
  const { View } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(View) };
});
jest.mock('lucide-react-native/icons/users-round', () => {
  const React = require('react') as typeof import('react');
  const { View } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(View) };
});
jest.mock('@/core/query/use-manual-refresh', () => ({
  useManualRefresh: () => ({
    isRefreshing: false,
    refresh: (task: () => Promise<unknown>) => task(),
  }),
}));
jest.mock('@/features/content/hooks/use-content', () => ({
  useReadiness: () => mockReadiness(),
}));
jest.mock('@/features/manager/hooks/use-manager-operations', () => ({
  useManagerAttendanceSessions: () => mockAttendance(),
}));
jest.mock('@/features/trips/hooks/use-trips', () => ({ useTrips: () => mockTrips() }));
jest.mock('@/features/trips/ui/trip-switcher', () => {
  const React = require('react') as typeof import('react');
  const { View } = require('react-native') as typeof import('react-native');
  return { TripSwitcher: () => React.createElement(View) };
});
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
jest.mock('@/design/components/screen', () => {
  const React = require('react') as typeof import('react');
  const { View } = require('react-native') as typeof import('react-native');
  return { Screen: ({ children }: { children: React.ReactNode }) => React.createElement(View, null, children) };
});

beforeEach(() => {
  jest.clearAllMocks();
  mockTrips.mockReturnValue({
    selectedTripId: '11111111-1111-4111-8111-111111111111',
    selectedTrip: { name: 'Enterprise Group' },
    trips: [],
    isPending: false,
    selectTrip: jest.fn(),
    refetch: jest.fn(async () => undefined),
  });
  mockReadiness.mockReturnValue({
    data: {
      passenger_count: 720,
      passports_complete: 720,
      visas_available: 510,
      tickets_available: 480,
      needs_attention: 0,
      rooms_assigned: 719,
      meals_confirmed: 0,
      updated_at: '2026-08-05T12:00:00.000Z',
      version: 4,
    },
    isPending: false,
    isError: false,
    refetch: jest.fn(async () => undefined),
  });
  mockAttendance.mockReturnValue({
    data: { items: [{ id: 'activity-a' }, { id: 'activity-b' }] },
    refetch: jest.fn(async () => undefined),
  });
});

test('shows exactly the four requested operational cards and removes legacy readiness metrics', async () => {
  const screen = await render(<ManagerReadinessScreen />);

  expect(screen.getAllByRole('button')).toHaveLength(4);
  expect(screen.getByLabelText('Total passengers, 720')).toBeTruthy();
  expect(screen.getByLabelText('Visas, 510')).toBeTruthy();
  expect(screen.getByLabelText('Flight tickets, 480')).toBeTruthy();
  expect(screen.getByLabelText('Attendance, 2')).toBeTruthy();
  expect(screen.queryByText(/passengers in this group/i)).toBeNull();
  expect(screen.queryByText(/need attention/i)).toBeNull();
  expect(screen.queryByText(/rooms assigned/i)).toBeNull();
  expect(screen.queryByText(/meals confirmed/i)).toBeNull();
});

test('opens the roster, server preview lists, and attendance activity screen', async () => {
  const screen = await render(<ManagerReadinessScreen />);

  await fireEvent.press(screen.getByLabelText('Total passengers, 720'));
  await fireEvent.press(screen.getByLabelText('Visas, 510'));
  await fireEvent.press(screen.getByLabelText('Flight tickets, 480'));
  await fireEvent.press(screen.getByLabelText('Attendance, 2'));

  expect(mockPush.mock.calls).toEqual([
    ['/(manager)/operations/passengers?mode=all'],
    ['/(manager)/operations/passengers?mode=visa'],
    ['/(manager)/operations/passengers?mode=flight_ticket'],
    ['/(manager)/operations/attendance'],
  ]);
});
