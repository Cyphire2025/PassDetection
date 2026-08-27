import { initialFaceScanState, reduceFaceScan } from '../face-scan-machine';

describe('Face Scan state machine', () => {
  it('moves through consent, permission, a single-use session, and verification', () => {
    let state = initialFaceScanState;
    state = reduceFaceScan(state, { type: 'CONTINUE' });
    expect(state.step).toBe('consent');
    state = reduceFaceScan(state, { type: 'CONSENT_ACCEPTED' });
    state = reduceFaceScan(state, { type: 'USE_MOVEMENT_ONLY' });
    state = reduceFaceScan(state, { type: 'CONTINUE' });
    state = reduceFaceScan(state, { type: 'CAMERA_GRANTED' });
    state = reduceFaceScan(state, { type: 'START' });
    state = reduceFaceScan(state, {
      type: 'SESSION_CREATED',
      clientFlow: 'development_simulator',
      sessionId: '3d78ff79-78f5-4618-aa1c-356d3e74ff4e',
      expiresAt: '2026-08-23T10:01:00Z',
    });
    expect(state).toMatchObject({
      step: 'running',
      challengeMode: 'movement_only',
      clientFlow: 'development_simulator',
    });
    state = reduceFaceScan(state, { type: 'NATIVE_COMPLETED' });
    state = reduceFaceScan(state, { type: 'VERIFIED' });
    expect(state).toEqual({ step: 'success' });
  });

  it.each([
    ['no_face', true],
    ['multiple_faces', true],
    ['session_expired', true],
    ['provider_unavailable', true],
    ['device_unsupported', false],
    ['camera_unavailable', false],
    ['front_camera_unavailable', false],
    ['nonrecoverable', false],
  ] as const)('represents %s explicitly', (reason, retryable) => {
    const state = reduceFaceScan(
      { step: 'ready', challengeMode: 'movement_and_light' },
      { type: 'FAILED', reason },
    );
    expect(state).toMatchObject({ step: 'failure', reason, retryable });
  });

  it('treats backgrounding during sensitive work as an interruption', () => {
    const state = reduceFaceScan(
      {
        step: 'running',
        challengeMode: 'movement_and_light',
        clientFlow: 'native',
        sessionId: 'session',
        expiresAt: '2026-08-23T10:01:00Z',
      },
      { type: 'APP_BACKGROUNDED' },
    );
    expect(state).toMatchObject({ step: 'failure', reason: 'backgrounded' });
  });

  it('retains a completed session when processing is interrupted in the background', () => {
    const state = reduceFaceScan(
      {
        step: 'processing',
        challengeMode: 'movement_only',
        sessionId: '3d78ff79-78f5-4618-aa1c-356d3e74ff4e',
      },
      { type: 'APP_BACKGROUNDED' },
    );

    expect(state).toMatchObject({
      step: 'failure',
      reason: 'backgrounded',
      pendingCompletion: {
        sessionId: '3d78ff79-78f5-4618-aa1c-356d3e74ff4e',
        outcome: 'completed',
      },
    });
    expect(reduceFaceScan(state, { type: 'RETRY' })).toEqual({
      step: 'processing',
      challengeMode: 'movement_only',
      sessionId: '3d78ff79-78f5-4618-aa1c-356d3e74ff4e',
    });
  });

  it('does not replace an ambiguous completed outcome with cancellation', () => {
    const state = reduceFaceScan(
      {
        step: 'processing',
        challengeMode: 'movement_only',
        sessionId: '3d78ff79-78f5-4618-aa1c-356d3e74ff4e',
      },
      { type: 'CANCEL' },
    );

    expect(state).toMatchObject({
      step: 'failure',
      reason: 'cancelled',
      pendingCompletion: {
        sessionId: '3d78ff79-78f5-4618-aa1c-356d3e74ff4e',
        outcome: 'completed',
      },
    });
  });

  it('replays a transient provider completion against the existing session', () => {
    const state = reduceFaceScan(
      {
        step: 'processing',
        challengeMode: 'movement_and_light',
        sessionId: '3d78ff79-78f5-4618-aa1c-356d3e74ff4e',
      },
      {
        type: 'FAILED',
        reason: 'provider_unavailable',
        retryable: true,
        pendingCompletion: {
          sessionId: '3d78ff79-78f5-4618-aa1c-356d3e74ff4e',
          outcome: 'completed',
        },
      },
    );

    expect(reduceFaceScan(state, { type: 'RETRY' })).toMatchObject({
      step: 'processing',
      sessionId: '3d78ff79-78f5-4618-aa1c-356d3e74ff4e',
    });
  });

  it('does not retry while a cooldown remains', () => {
    const state = reduceFaceScan(
      {
        step: 'failure',
        challengeMode: 'movement_and_light',
        reason: 'rate_limited',
        retryable: true,
        retryAfterSeconds: 60,
      },
      { type: 'RETRY' },
    );
    expect(state.step).toBe('failure');
    expect(reduceFaceScan(state, { type: 'COOLDOWN_EXPIRED' })).toEqual({
      step: 'ready',
      challengeMode: 'movement_and_light',
    });
  });
});
