/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories load mocked host components after hoisting. */
import { act, fireEvent, render, waitFor } from '@testing-library/react-native';
import { Alert } from 'react-native';

import { requestSync } from '@/core/sync/sync-trigger';
import {
  acknowledgeAttendanceNeedsReview,
  acknowledgeRejectedAttendance,
  listAttendanceNeedsReview,
  retryAttendanceNeedsReview,
} from '@/features/coordinator/data/attendance-queue';
import { listRejectedAttendanceIssues } from '@/features/coordinator/data/attendance-scan-issues';

import CoordinatorScanIssuesScreen from '../scan-issues';

const TRIP = '11111111-1111-4111-8111-111111111111';
const REVIEW_EVENT = '22222222-2222-4222-8222-222222222222';
const REJECTED_EVENT = '33333333-3333-4333-8333-333333333333';

jest.mock('@/core/query/use-route-focus', () => ({ useRouteFocus: () => true }));
jest.mock('@/core/sync/sync-trigger', () => ({ requestSync: jest.fn() }));
jest.mock('@/features/coordinator/hooks/use-coordinator-trips', () => ({
  useCoordinatorTrips: () => ({
    selectedTripId: '11111111-1111-4111-8111-111111111111',
    selectedTrip: { name: 'Enterprise Group' },
  }),
}));
jest.mock('@/features/coordinator/data/attendance-queue', () => ({
  acknowledgeAttendanceNeedsReview: jest.fn(),
  acknowledgeRejectedAttendance: jest.fn(),
  listAttendanceNeedsReview: jest.fn(),
  retryAttendanceNeedsReview: jest.fn(),
}));
jest.mock('@/features/coordinator/data/attendance-discard-store', () => ({
  attendanceDiscardAuditStatus: jest.fn().mockResolvedValue({
    pending: 1,
    rejected: 0,
    synchronized: 2,
  }),
  drainAttendanceDiscardTombstones: jest.fn().mockResolvedValue({
    pending: 0,
    rejected: 0,
    synchronized: 3,
  }),
}));
jest.mock('@/features/coordinator/data/attendance-scan-issues', () => {
  const actual = jest.requireActual('@/features/coordinator/data/attendance-scan-issues') as object;
  return { ...actual, listRejectedAttendanceIssues: jest.fn() };
});
jest.mock('@/features/coordinator/ui/operation-header', () => {
  const React = require('react') as typeof import('react');
  const { Text } = require('react-native') as typeof import('react-native');
  return { OperationHeader: ({ title }: { title: string }) => React.createElement(Text, null, title) };
});
jest.mock('@/design/components/screen', () => {
  const React = require('react') as typeof import('react');
  const { View } = require('react-native') as typeof import('react-native');
  return { Screen: ({ children }: { children: React.ReactNode }) => React.createElement(View, null, children) };
});
jest.mock('@/design/components/primary-button', () => {
  const React = require('react') as typeof import('react');
  const { Pressable, Text } = require('react-native') as typeof import('react-native');
  return {
    PrimaryButton: ({ label, onPress, disabled }: {
      label: string;
      onPress: () => void;
      disabled?: boolean;
    }) => React.createElement(
      Pressable,
      { accessibilityRole: 'button', disabled, onPress },
      React.createElement(Text, null, label),
    ),
  };
});
jest.mock('@/design/components/content-state', () => {
  const React = require('react') as typeof import('react');
  const { Text } = require('react-native') as typeof import('react-native');
  const State = ({ title, message, label }: {
    title?: string;
    message?: string;
    label?: string;
  }) => React.createElement(Text, null, title ?? message ?? label ?? '');
  return { ContentEmpty: State, ContentError: State, ContentLoading: State };
});

const mockedSync = jest.mocked(requestSync);
const mockedListReview = jest.mocked(listAttendanceNeedsReview);
const mockedListRejected = jest.mocked(listRejectedAttendanceIssues);
const mockedRetry = jest.mocked(retryAttendanceNeedsReview);
const mockedDiscard = jest.mocked(acknowledgeAttendanceNeedsReview);
const mockedAcknowledgeRejected = jest.mocked(acknowledgeRejectedAttendance);

beforeEach(() => {
  jest.clearAllMocks();
  mockedSync.mockResolvedValue({
    results: [],
    failures: [],
    requestedTripCount: 0,
    tripsChanged: false,
    removedTripIds: [],
  });
  mockedRetry.mockResolvedValue({
    settledBySession: {},
    confirmedBySession: {},
    newlyAcceptedBySession: {},
    rejectedBySession: {},
  });
  mockedDiscard.mockResolvedValue(true);
  mockedAcknowledgeRejected.mockResolvedValue(1);
  mockedListReview.mockResolvedValue([{
    idempotencyKey: REVIEW_EVENT,
    sessionId: '44444444-4444-4444-8444-444444444444',
    reasonCode: 'REFRESH_REQUIRED',
    createdAt: '2030-01-02T11:00:00.000Z',
    updatedAt: '2030-01-02T11:01:00.000Z',
    attemptCount: 2,
    passengerLabel: 'Passenger One',
    safeReference: 'ABCDEF123456',
    sessionLabel: 'Airport departure',
    retryState: 'ready_to_retry',
    lastAttemptAt: '2030-01-02T11:01:00.000Z',
  }]);
  mockedListRejected.mockResolvedValue([{
    idempotencyKey: REJECTED_EVENT,
    reasonCode: 'QR_INVALID',
    createdAt: '2030-01-02T10:00:00.000Z',
    updatedAt: '2030-01-02T10:01:00.000Z',
    attemptCount: 1,
    passengerLabel: 'Passenger Two',
    safeReference: '987654FEDCBA',
    sessionLabel: 'Hotel arrival',
    retryState: 'terminal',
    lastAttemptAt: '2030-01-02T10:01:00.000Z',
  }]);
});

afterEach(() => {
  jest.restoreAllMocks();
});

async function renderIssues() {
  let result!: ReturnType<typeof render>;
  await act(async () => {
    result = render(<CoordinatorScanIssuesScreen />);
    await Promise.resolve();
    await Promise.resolve();
  });
  return result;
}

test('shows persistent safe issue metadata and retries with sync first', async () => {
  const screen = await renderIssues();
  await waitFor(() => expect(screen.getByText('2 unresolved records')).toBeTruthy());
  expect(screen.getByText(/roster or activity changed/i)).toBeTruthy();
  expect(screen.getByText(/invalid, expired, revoked/i)).toBeTruthy();
  expect(screen.queryByText('REFRESH_REQUIRED')).toBeNull();
  expect(screen.queryByText('QR_INVALID')).toBeNull();

  await act(async () => {
    await fireEvent.press(screen.getByText('Sync and retry'));
    await Promise.resolve();
    await Promise.resolve();
  });
  await waitFor(() => expect(mockedSync).toHaveBeenCalledWith({
    scope: 'trip',
    tripId: TRIP,
    reason: 'manual-scan-issue-retry',
  }));
  expect(mockedRetry).toHaveBeenCalledWith(TRIP, REVIEW_EVENT);
});

test('requires explicit destructive confirmation before either issue record is removed', async () => {
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  const screen = await renderIssues();
  await waitFor(() => expect(screen.getByText('Discard saved scan')).toBeTruthy());

  await fireEvent.press(screen.getByText('Discard saved scan'));
  expect(mockedDiscard).not.toHaveBeenCalled();
  await act(async () => {
    alert.mock.calls[0]?.[2]?.find((button) => button.text === 'Discard scan')?.onPress?.();
    await Promise.resolve();
    await Promise.resolve();
  });
  await waitFor(() => expect(mockedDiscard).toHaveBeenCalledWith(TRIP, REVIEW_EVENT));

  await fireEvent.press(screen.getByText('Acknowledge terminal issues'));
  expect(mockedAcknowledgeRejected).not.toHaveBeenCalled();
  await act(async () => {
    alert.mock.calls[1]?.[2]?.find((button) => button.text === 'Acknowledge issues')?.onPress?.();
    await Promise.resolve();
    await Promise.resolve();
  });
  await waitFor(() => expect(mockedAcknowledgeRejected).toHaveBeenCalledWith(TRIP));
});
