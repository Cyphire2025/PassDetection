import { faceScanCloseDecision } from '../face-scan-navigation-policy';

it.each(['starting', 'processing'] as const)(
  'keeps the Face Scan route mounted when %s is transport-ambiguous',
  (step) => {
    expect(faceScanCloseDecision(step)).toBe('cancel_and_stay_for_recovery');
  },
);

it.each(['ready', 'running', 'failure', 'success'] as const)(
  'allows an explicit cancel to close from %s',
  (step) => {
    expect(faceScanCloseDecision(step)).toBe('cancel_and_close');
  },
);
