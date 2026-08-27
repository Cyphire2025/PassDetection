export type FaceScanFailure =
  | 'camera_denied'
  | 'camera_blocked'
  | 'camera_unavailable'
  | 'front_camera_unavailable'
  | 'no_face'
  | 'multiple_faces'
  | 'face_too_close'
  | 'face_too_far'
  | 'poor_lighting'
  | 'excessive_movement'
  | 'network_interrupted'
  | 'session_expired'
  | 'liveness_rejected'
  | 'provider_timeout'
  | 'provider_unavailable'
  | 'rate_limited'
  | 'device_unsupported'
  | 'cancelled'
  | 'backgrounded'
  | 'nonrecoverable';

export type FaceScanChallengeMode = 'movement_and_light' | 'movement_only';
export type FaceScanClientFlow = 'development_simulator' | 'native';
export type FaceScanPendingCompletion = Readonly<{
  sessionId: string;
  outcome: 'completed';
}>;

export type FaceScanState =
  | Readonly<{ step: 'explanation' }>
  | Readonly<{ step: 'consent' }>
  | Readonly<{ step: 'preparation'; challengeMode: FaceScanChallengeMode }>
  | Readonly<{ step: 'camera_permission'; challengeMode: FaceScanChallengeMode }>
  | Readonly<{ step: 'ready'; challengeMode: FaceScanChallengeMode }>
  | Readonly<{ step: 'starting'; challengeMode: FaceScanChallengeMode }>
  | Readonly<{
      step: 'running';
      challengeMode: FaceScanChallengeMode;
      clientFlow: FaceScanClientFlow;
      sessionId: string;
      expiresAt: string;
    }>
  | Readonly<{
      step: 'processing';
      challengeMode: FaceScanChallengeMode;
      sessionId: string;
    }>
  | Readonly<{ step: 'success' }>
  | Readonly<{
      step: 'failure';
      challengeMode: FaceScanChallengeMode;
      reason: FaceScanFailure;
      retryable: boolean;
      retryAfterSeconds: number | null;
      pendingCompletion?: FaceScanPendingCompletion;
    }>;

export type FaceScanEvent =
  | Readonly<{ type: 'CONTINUE' }>
  | Readonly<{ type: 'CONSENT_ACCEPTED' }>
  | Readonly<{ type: 'USE_MOVEMENT_ONLY' }>
  | Readonly<{ type: 'USE_MOVEMENT_AND_LIGHT' }>
  | Readonly<{ type: 'CAMERA_GRANTED' }>
  | Readonly<{ type: 'CAMERA_DENIED'; canAskAgain: boolean }>
  | Readonly<{ type: 'START' }>
  | Readonly<{
      type: 'SESSION_CREATED';
      clientFlow: FaceScanClientFlow;
      sessionId: string;
      expiresAt: string;
    }>
  | Readonly<{ type: 'NATIVE_COMPLETED' }>
  | Readonly<{ type: 'COMPLETION_RETRY_STARTED'; sessionId: string }>
  | Readonly<{ type: 'VERIFIED' }>
  | Readonly<{
      type: 'FAILED';
      reason: FaceScanFailure;
      retryable?: boolean;
      retryAfterSeconds?: number | null;
      pendingCompletion?: FaceScanPendingCompletion;
    }>
  | Readonly<{ type: 'CANCEL' }>
  | Readonly<{ type: 'APP_BACKGROUNDED' }>
  | Readonly<{ type: 'COOLDOWN_EXPIRED' }>
  | Readonly<{ type: 'RETRY' }>
  | Readonly<{ type: 'RESET' }>;

export const initialFaceScanState: FaceScanState = Object.freeze({ step: 'explanation' });

function currentMode(state: FaceScanState): FaceScanChallengeMode {
  return 'challengeMode' in state ? state.challengeMode : 'movement_and_light';
}

function isIntrinsicallyNonretryable(reason: FaceScanFailure): boolean {
  return reason === 'device_unsupported'
    || reason === 'camera_unavailable'
    || reason === 'front_camera_unavailable'
    || reason === 'nonrecoverable';
}

function failure(
  state: FaceScanState,
  reason: FaceScanFailure,
  retryable = true,
  retryAfterSeconds: number | null = null,
  pendingCompletion?: FaceScanPendingCompletion,
): FaceScanState {
  return {
    step: 'failure',
    challengeMode: currentMode(state),
    reason,
    retryable,
    retryAfterSeconds,
    ...(pendingCompletion ? { pendingCompletion } : {}),
  };
}

/** Pure, exhaustive Face Scan lifecycle. Capture retries obtain a fresh
 * single-use session; an ambiguous completion replays the same session and
 * idempotency identity until the server resolves it. */
export function reduceFaceScan(state: FaceScanState, event: FaceScanEvent): FaceScanState {
  if (event.type === 'RESET') return initialFaceScanState;
  if (event.type === 'FAILED') {
    return failure(
      state,
      event.reason,
      isIntrinsicallyNonretryable(event.reason) ? false : event.retryable ?? true,
      event.retryAfterSeconds ?? null,
      event.pendingCompletion,
    );
  }
  if (event.type === 'CANCEL') {
    if (state.step === 'processing') {
      return failure(state, 'cancelled', true, null, {
        sessionId: state.sessionId,
        outcome: 'completed',
      });
    }
    return failure(state, 'cancelled');
  }
  if (event.type === 'APP_BACKGROUNDED') {
    if (state.step === 'processing') {
      return failure(state, 'backgrounded', true, null, {
        sessionId: state.sessionId,
        outcome: 'completed',
      });
    }
    return state.step === 'starting' || state.step === 'running'
      ? failure(state, 'backgrounded') : state;
  }
  switch (state.step) {
    case 'explanation':
      return event.type === 'CONTINUE' ? { step: 'consent' } : state;
    case 'consent':
      return event.type === 'CONSENT_ACCEPTED'
        ? { step: 'preparation', challengeMode: 'movement_and_light' }
        : state;
    case 'preparation':
      if (event.type === 'USE_MOVEMENT_ONLY') {
        return { ...state, challengeMode: 'movement_only' };
      }
      if (event.type === 'USE_MOVEMENT_AND_LIGHT') {
        return { ...state, challengeMode: 'movement_and_light' };
      }
      return event.type === 'CONTINUE'
        ? { step: 'camera_permission', challengeMode: state.challengeMode }
        : state;
    case 'camera_permission':
      if (event.type === 'CAMERA_GRANTED') {
        return { step: 'ready', challengeMode: state.challengeMode };
      }
      if (event.type === 'CAMERA_DENIED') {
        return failure(state, event.canAskAgain ? 'camera_denied' : 'camera_blocked');
      }
      return state;
    case 'ready':
      return event.type === 'START'
        ? { step: 'starting', challengeMode: state.challengeMode }
        : state;
    case 'starting':
      return event.type === 'SESSION_CREATED'
        ? {
            step: 'running',
            challengeMode: state.challengeMode,
            clientFlow: event.clientFlow,
            sessionId: event.sessionId,
            expiresAt: event.expiresAt,
          }
        : state;
    case 'running':
      return event.type === 'NATIVE_COMPLETED'
        ? { step: 'processing', challengeMode: state.challengeMode, sessionId: state.sessionId }
        : state;
    case 'processing':
      return event.type === 'VERIFIED' ? { step: 'success' } : state;
    case 'failure':
      if (event.type === 'COMPLETION_RETRY_STARTED' && state.pendingCompletion) {
        return {
          step: 'processing',
          challengeMode: state.challengeMode,
          sessionId: event.sessionId,
        };
      }
      if (
        event.type === 'COOLDOWN_EXPIRED'
        && state.retryable
      ) {
        if (state.pendingCompletion) return { ...state, retryAfterSeconds: null };
        if (state.reason !== 'rate_limited' && state.reason !== 'liveness_rejected') return state;
        return { step: 'ready', challengeMode: state.challengeMode };
      }
      if (event.type === 'RETRY' && state.pendingCompletion && !state.retryAfterSeconds) {
        return {
          step: 'processing',
          challengeMode: state.challengeMode,
          sessionId: state.pendingCompletion.sessionId,
        };
      }
      return event.type === 'RETRY' && state.retryable && !state.retryAfterSeconds
        ? { step: 'ready', challengeMode: state.challengeMode }
        : state;
    case 'success':
      return state;
  }
}
