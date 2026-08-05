/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories load mocked host components after hoisting. */
import { fireEvent, render, waitFor } from '@testing-library/react-native';

import { selectAttendanceSession } from '@/features/coordinator/data/attendance-sessions';
import { useAttendanceSessions } from '@/features/coordinator/hooks/use-coordinator';
import { useCoordinatorTrips } from '@/features/coordinator/hooks/use-coordinator-trips';

import CoordinatorScanScreen from '../scan';

const mockCameraRender = jest.fn();

jest.mock('expo-camera', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return {
    CameraView: () => {
      mockCameraRender();
      return React.createElement(MockView, { testID: 'attendance-camera' });
    },
    useCameraPermissions: () => [{ granted: true }, jest.fn()],
  };
});
jest.mock('expo-haptics', () => ({
  NotificationFeedbackType: { Error: 'error', Success: 'success', Warning: 'warning' },
  notificationAsync: jest.fn(async () => undefined),
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
  drainAttendanceQueue: jest.fn(async () => undefined),
  enqueueQrScan: jest.fn(),
}));
jest.mock('@/features/coordinator/data/attendance-sessions', () => ({
  createAttendanceSession: jest.fn(),
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
jest.mock('@/design/components/text-field', () => {
  const React = require('react') as typeof import('react');
  const { TextInput: MockTextInput } = require('react-native') as typeof import('react-native');
  return {
    TextField: (props: Record<string, unknown>) => React.createElement(MockTextInput, props),
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

beforeEach(() => {
  jest.clearAllMocks();
  mockedUseCoordinatorTrips.mockReturnValue({
    selectedTripId: '11111111-1111-4111-8111-111111111111',
    selectedTrip: { name: 'Enterprise Group' },
  } as ReturnType<typeof useCoordinatorTrips>);
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

test('does not refresh while an unsaved activity name is present', async () => {
  const refetch = jest.fn(async () => undefined);
  mockedUseAttendanceSessions.mockReturnValue({
    data: {
      items: [],
      selectedSessionId: null,
    },
    isPending: false,
    isError: false,
    refetch,
  } as unknown as ReturnType<typeof useAttendanceSessions>);

  const screen = await render(<CoordinatorScanScreen />);
  const activityList = screen.getByTestId('scan-activity-list');

  await fireEvent(activityList, 'refresh');
  expect(refetch).toHaveBeenCalledTimes(1);
  refetch.mockClear();

  await fireEvent.changeText(screen.getByPlaceholderText('Airport reporting'), 'Dinner');
  await fireEvent(screen.getByTestId('scan-activity-list'), 'refresh');

  expect(refetch).not.toHaveBeenCalled();
});
