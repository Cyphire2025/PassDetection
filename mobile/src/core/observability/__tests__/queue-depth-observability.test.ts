import { recordMobileMetric } from '../mobile-observability';
import { recordTripDurableQueueDepths } from '../queue-depth-observability';

jest.mock('../mobile-observability', () => ({ recordMobileMetric: jest.fn() }));

const mockedRecordMetric = jest.mocked(recordMobileMetric);

beforeEach(() => {
  jest.clearAllMocks();
});

afterEach(() => {
  jest.restoreAllMocks();
});

test('records only aggregate attendance and document queue depths', async () => {
  jest.spyOn(Date, 'now').mockReturnValue(Date.parse('2030-01-01T00:01:00.000Z'));
  const database = {
    getFirstAsync: jest.fn().mockResolvedValue({
      attendance_depth: 7,
      attendance_needs_review_depth: 2,
      attendance_oldest_created_at: '2030-01-01T00:00:00.000Z',
      document_depth: 3,
    }),
  };

  await recordTripDurableQueueDepths(
    database as never,
    'agency.principal',
    '11111111-1111-4111-8111-111111111111',
  );

  expect(database.getFirstAsync).toHaveBeenCalledWith(
    expect.stringContaining("action_type = 'attendance.scan'"),
    'agency.principal',
    '11111111-1111-4111-8111-111111111111',
    'agency.principal',
    '11111111-1111-4111-8111-111111111111',
    'agency.principal',
    '11111111-1111-4111-8111-111111111111',
    'agency.principal',
    '11111111-1111-4111-8111-111111111111',
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    1,
    'queue_depth',
    7,
    { queue: 'attendance' },
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    2,
    'attendance_oldest_pending_age',
    60_000,
    { queue: 'attendance' },
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    3,
    'attendance_needs_review_depth',
    2,
    { queue: 'attendance' },
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    4,
    'queue_depth',
    3,
    { queue: 'documents' },
  );
});

test('reports zero age for an empty attendance queue and omits an invalid future age', async () => {
  jest.spyOn(Date, 'now').mockReturnValue(Date.parse('2030-01-01T00:00:00.000Z'));
  const database = {
    getFirstAsync: jest.fn()
      .mockResolvedValueOnce({
        attendance_depth: 0,
        attendance_needs_review_depth: 0,
        attendance_oldest_created_at: null,
        document_depth: 0,
      })
      .mockResolvedValueOnce({
        attendance_depth: 1,
        attendance_needs_review_depth: 0,
        attendance_oldest_created_at: '2030-01-01T00:00:01.000Z',
        document_depth: 0,
      }),
  };

  await recordTripDurableQueueDepths(database as never, 'agency.principal', 'trip-one');
  expect(mockedRecordMetric).toHaveBeenCalledWith(
    'attendance_oldest_pending_age',
    0,
    { queue: 'attendance' },
  );

  mockedRecordMetric.mockClear();
  await recordTripDurableQueueDepths(database as never, 'agency.principal', 'trip-one');
  expect(mockedRecordMetric).not.toHaveBeenCalledWith(
    'attendance_oldest_pending_age',
    expect.anything(),
    expect.anything(),
  );
});

test('contains database failures so telemetry cannot fail synchronization', async () => {
  const database = {
    getFirstAsync: jest.fn().mockRejectedValue(new Error('database unavailable')),
  };

  await expect(recordTripDurableQueueDepths(
    database as never,
    'agency.principal',
    '11111111-1111-4111-8111-111111111111',
  )).resolves.toBeUndefined();
  expect(mockedRecordMetric).not.toHaveBeenCalled();
});
