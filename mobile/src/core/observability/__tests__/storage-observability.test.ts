import { recordMobileMetric } from '../mobile-observability';
import { recordStorageMaintenance } from '../storage-observability';

jest.mock('../mobile-observability', () => ({ recordMobileMetric: jest.fn() }));

const mockedRecordMetric = jest.mocked(recordMobileMetric);

beforeEach(() => jest.clearAllMocks());

test('records bounded count-only storage maintenance evidence', () => {
  recordStorageMaintenance(2_500, 42, 'success');

  expect(mockedRecordMetric.mock.calls).toEqual([
    [
      'storage_maintenance_duration',
      2_500,
      { outcome: 'success', trigger: 'background' },
    ],
    [
      'storage_maintenance_run',
      1,
      { outcome: 'success', trigger: 'background' },
    ],
    [
      'storage_maintenance_changes',
      42,
      { outcome: 'success', trigger: 'background' },
    ],
  ]);
});

test('failure evidence never claims that uncommitted rows were changed', () => {
  recordStorageMaintenance(120_001, 15, 'failure');

  expect(mockedRecordMetric.mock.calls).toEqual([
    [
      'storage_maintenance_duration',
      120_000,
      { outcome: 'failure', trigger: 'background' },
    ],
    [
      'storage_maintenance_run',
      1,
      { outcome: 'failure', trigger: 'background' },
    ],
  ]);
});

test.each([
  [Number.NaN, 0],
  [-1, 0],
  [1, -1],
  [1, 1.5],
])('drops invalid evidence without throwing (%p, %p)', (durationMs, changedRows) => {
  expect(() => recordStorageMaintenance(durationMs, changedRows, 'success')).not.toThrow();
  expect(mockedRecordMetric).not.toHaveBeenCalled();
});

test('contains a metric transport failure', () => {
  mockedRecordMetric.mockImplementationOnce(() => {
    throw new Error('transport unavailable');
  });
  expect(() => recordStorageMaintenance(5, 1, 'success')).not.toThrow();
});
