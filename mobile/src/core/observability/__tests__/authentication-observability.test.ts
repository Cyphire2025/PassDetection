import { recordMobileMetric } from '../mobile-observability';
import {
  recordAuthenticationLockOutcome,
  recordAuthenticationQuarantineDepth,
} from '../authentication-observability';

jest.mock('../mobile-observability', () => ({ recordMobileMetric: jest.fn() }));

const mockedRecordMetric = jest.mocked(recordMobileMetric);

beforeEach(() => {
  jest.clearAllMocks();
});

test('records count-only authentication lock and quarantine evidence', () => {
  recordAuthenticationLockOutcome('failure');
  recordAuthenticationQuarantineDepth(3);

  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    1,
    'authentication_lock',
    1,
    { outcome: 'failure', trigger: 'mutation' },
  );
  expect(mockedRecordMetric).toHaveBeenNthCalledWith(
    2,
    'authentication_quarantine_depth',
    3,
    { trigger: 'startup' },
  );
});

test('clamps aggregate quarantine depth and drops invalid values', () => {
  recordAuthenticationLockOutcome('secret' as never);
  recordAuthenticationQuarantineDepth(101);
  recordAuthenticationQuarantineDepth(-1);
  recordAuthenticationQuarantineDepth(1.5);

  expect(mockedRecordMetric).toHaveBeenCalledTimes(1);
  expect(mockedRecordMetric).toHaveBeenCalledWith(
    'authentication_quarantine_depth',
    100,
    { trigger: 'startup' },
  );
});

test('never changes lock behavior when telemetry throws', () => {
  mockedRecordMetric.mockImplementationOnce(() => {
    throw new Error('metrics unavailable');
  });

  expect(() => recordAuthenticationLockOutcome('success')).not.toThrow();
});
