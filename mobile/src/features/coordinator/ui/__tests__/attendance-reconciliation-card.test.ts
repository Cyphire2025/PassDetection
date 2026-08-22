import { assessAttendanceReconciliation } from '../attendance-reconciliation-card';

const clearQueue = {
  awaitingConfirmation: 0,
  needsReview: 0,
  pending: 0,
  retryable: 0,
  sending: 0,
};

test('is green only when the confirmed count matches expected and the device queue is clear', () => {
  expect(assessAttendanceReconciliation(800, 800, clearQueue)).toEqual({
    confirmed: 800,
    expected: 800,
    message: 'Server-confirmed count matches the assigned count and this device queue is clear.',
    missing: 0,
    status: 'ready',
  });
});

test.each([
  ['queue evidence is unavailable', 800, 800, null, 'could not be verified'],
  ['saved scans await confirmation', 799, 800, {
    ...clearQueue,
    awaitingConfirmation: 1,
    pending: 1,
  }, 'await server confirmation'],
  ['scan issues remain', 800, 800, {
    ...clearQueue,
    needsReview: 2,
  }, 'must be resolved'],
  ['assigned passengers remain', 799, 800, clearQueue, 'remain unconfirmed'],
  ['server count exceeds assigned count', 801, 800, clearQueue, 'could not be verified'],
] as const)('blocks closeout when %s', (_label, confirmed, expected, queue, copy) => {
  const assessment = assessAttendanceReconciliation(confirmed, expected, queue);
  expect(assessment.status).toBe('blocked');
  expect(assessment.message).toContain(copy);
});
