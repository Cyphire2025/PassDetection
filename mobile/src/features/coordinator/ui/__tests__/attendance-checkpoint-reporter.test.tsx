import { act, cleanup, render } from '@testing-library/react-native';

import { recordAttendanceReconciliationAssessment } from '@/core/observability/attendance-observability';
import { publishAttendanceCloseoutCheckpoint } from '@/features/coordinator/data/attendance-closeout-checkpoint';
import { attendanceSessionQueueStatus } from '@/features/coordinator/data/attendance-queue';

import { AttendanceCheckpointReporter } from '../attendance-checkpoint-reporter';

let mockFocused = true;

jest.mock('@/core/query/use-route-focus', () => ({
  useRouteFocus: () => mockFocused,
}));
jest.mock('@/core/observability/attendance-observability', () => ({
  recordAttendanceReconciliationAssessment: jest.fn(),
}));
jest.mock('@/features/coordinator/data/attendance-closeout-checkpoint', () => ({
  publishAttendanceCloseoutCheckpoint: jest.fn(async () => undefined),
}));
jest.mock('@/features/coordinator/data/attendance-queue', () => ({
  attendanceSessionQueueStatus: jest.fn(async () => ({
    awaitingConfirmation: 0,
    needsReview: 0,
    pending: 0,
    retryable: 0,
    sending: 0,
  })),
}));

const mockedRecordAssessment = jest.mocked(recordAttendanceReconciliationAssessment);
const mockedPublishCheckpoint = jest.mocked(publishAttendanceCloseoutCheckpoint);
const mockedQueueStatus = jest.mocked(attendanceSessionQueueStatus);

const tripId = '11111111-1111-4111-8111-111111111111';
const activeSession = {
  assigned_count: 100,
  completed_at: null,
  id: '22222222-2222-4222-8222-222222222222',
  name: 'Airport reporting',
  scanned_count: 92,
  started_at: '2030-01-01T00:00:00.000Z',
  status: 'active' as const,
};

async function flushEffects() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  mockFocused = true;
});

afterEach(async () => {
  await cleanup();
  jest.clearAllTimers();
  jest.useRealTimers();
});

test('renders nothing while publishing an immediate and 30-second closeout checkpoint', async () => {
  const screen = await render(
    <AttendanceCheckpointReporter tripId={tripId} session={activeSession} />,
  );
  expect(screen.toJSON()).toBeNull();

  await flushEffects();
  expect(mockedQueueStatus).toHaveBeenCalledWith(tripId, activeSession.id);
  expect(mockedRecordAssessment).toHaveBeenCalledWith(92, 100, {
    awaitingConfirmation: 0,
    needsReview: 0,
    pending: 0,
    retryable: 0,
    sending: 0,
  });
  expect(mockedPublishCheckpoint).toHaveBeenCalledTimes(1);

  await act(async () => {
    jest.advanceTimersByTime(30_000);
    await Promise.resolve();
  });
  expect(mockedPublishCheckpoint).toHaveBeenCalledTimes(2);

  await screen.unmount();
  await act(async () => {
    jest.advanceTimersByTime(60_000);
  });
  expect(mockedPublishCheckpoint).toHaveBeenCalledTimes(2);
});

test('does not publish checkpoints for a completed activity', async () => {
  const completedSession = {
    ...activeSession,
    completed_at: '2030-01-01T01:00:00.000Z',
    status: 'completed' as const,
  };
  const screen = await render(
    <AttendanceCheckpointReporter tripId={tripId} session={completedSession} />,
  );

  await flushEffects();
  expect(screen.toJSON()).toBeNull();
  expect(mockedQueueStatus).toHaveBeenCalledTimes(1);
  expect(mockedPublishCheckpoint).not.toHaveBeenCalled();
});

test('does no work while the attendance route is not focused', async () => {
  mockFocused = false;
  const screen = await render(
    <AttendanceCheckpointReporter tripId={tripId} session={activeSession} />,
  );

  await flushEffects();
  expect(screen.toJSON()).toBeNull();
  expect(mockedQueueStatus).not.toHaveBeenCalled();
  expect(mockedRecordAssessment).not.toHaveBeenCalled();
  expect(mockedPublishCheckpoint).not.toHaveBeenCalled();
});

test('keeps the coordinator UI empty when checkpoint publication fails', async () => {
  mockedPublishCheckpoint.mockRejectedValueOnce(new Error('offline'));
  const screen = await render(
    <AttendanceCheckpointReporter tripId={tripId} session={activeSession} />,
  );

  await flushEffects();
  expect(screen.toJSON()).toBeNull();
  expect(mockedPublishCheckpoint).toHaveBeenCalledTimes(1);
});
