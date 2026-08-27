import type { FaceScanState } from '../model/face-scan-machine';

export type FaceScanCloseDecision = 'cancel_and_close' | 'cancel_and_stay_for_recovery';

/** Session creation and completion are transport-ambiguous. The screen must
 * remain mounted so the retained idempotency identity can resolve/replay. */
export function faceScanCloseDecision(step: FaceScanState['step']): FaceScanCloseDecision {
  return step === 'starting' || step === 'processing'
    ? 'cancel_and_stay_for_recovery'
    : 'cancel_and_close';
}
