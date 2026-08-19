import { recordMobileMetric } from '../mobile-observability';
import { recordTripDurableQueueDepths } from '../queue-depth-observability';

jest.mock('../mobile-observability', () => ({ recordMobileMetric: jest.fn() }));

const mockedRecordMetric = jest.mocked(recordMobileMetric);

beforeEach(() => {
  jest.clearAllMocks();
});

test('records only aggregate attendance and document queue depths', async () => {
  const database = {
    getFirstAsync: jest.fn().mockResolvedValue({
      attendance_depth: 7,
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
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    1,
    'queue_depth',
    7,
    { queue: 'attendance' },
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    2,
    'queue_depth',
    3,
    { queue: 'documents' },
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
