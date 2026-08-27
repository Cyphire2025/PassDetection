import { useCameraPermissions } from 'expo-camera';
import { randomUUID } from 'expo-crypto';
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useReducer,
  useRef,
  useState,
} from 'react';
import { AppState } from 'react-native';

import { ApiError } from '@/core/api/client';
import { recordMobileMetric } from '@/core/observability/mobile-observability';

import type { ChallengeModeSchema } from '../api/contracts';
import { completeLivenessSession, startLivenessSession } from '../api/my-photos-api';
import { withMyPhotosContext } from '../data/my-photos-context';
import {
  assertDevelopmentLivenessSimulatorAllowed,
  nativeFaceLivenessBridge,
  type NativeFaceLivenessBridge,
  type NativeLivenessOutcome,
} from '../liveness/liveness-client';
import {
  FaceScanStartGate,
  faceScanStartDisposition,
} from '../liveness/face-scan-start-gate';
import {
  faceScanFailureFromStableCode,
  shouldReplayLivenessCompletion,
  shouldReplayLivenessCompletionResult,
} from '../liveness/face-scan-error-policy';
import {
  initialFaceScanState,
  reduceFaceScan,
  type FaceScanEvent,
  type FaceScanFailure,
} from '../model/face-scan-machine';
import { useMyPhotosMutations, useMyPhotosSummary } from './use-my-photos';
import type { z } from 'zod';

type FailureEvent = Extract<FaceScanEvent, { type: 'FAILED' }>;
const MAX_LIVENESS_SESSION_LIFETIME_MS = 3 * 60_000;

function boundedCooldownSeconds(value: number | null): number {
  return Math.min(3_600, Math.max(1, Number.isSafeInteger(value) ? value! : 60));
}

export function faceScanFailureEventFromError(error: unknown): FailureEvent {
  if (error instanceof ApiError) {
    const reason = faceScanFailureFromStableCode(error.code);
    if (error.status === 429 || reason === 'rate_limited') {
      return {
        type: 'FAILED',
        reason: 'rate_limited',
        retryable: true,
        retryAfterSeconds: boundedCooldownSeconds(error.retryAfterSeconds),
      };
    }
    if (reason) return { type: 'FAILED', reason };
    if (error.status === 0 || error.code === 'NETWORK_ERROR') {
      return { type: 'FAILED', reason: 'network_interrupted' };
    }
    if (error.status >= 500) return { type: 'FAILED', reason: 'provider_unavailable' };
  }
  if (error instanceof TypeError) return { type: 'FAILED', reason: 'network_interrupted' };
  if (error instanceof Error) {
    if (error.name === 'TimeoutError') return { type: 'FAILED', reason: 'provider_timeout' };
    if (error.name === 'AbortError') return { type: 'FAILED', reason: 'network_interrupted' };
  }
  return { type: 'FAILED', reason: 'nonrecoverable' };
}

export function shouldRetainFaceScanStartIdempotencyKey(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.status === 0
      || error.status === 408
      || error.status >= 500
      || error.code === 'NETWORK_ERROR';
  }
  return error instanceof TypeError || (
    error instanceof Error
    && (error.name === 'TimeoutError' || error.name === 'AbortError')
  );
}

function failureFromOutcome(outcome: NativeLivenessOutcome): FaceScanFailure {
  if (outcome === 'cancelled') return 'cancelled';
  if (outcome === 'expired') return 'session_expired';
  if (outcome === 'unavailable') return 'device_unsupported';
  return 'liveness_rejected';
}

export function useFaceScanController(
  tripId: string | null,
  nativeBridge: NativeFaceLivenessBridge = nativeFaceLivenessBridge,
) {
  const [state, dispatch] = useReducer(reduceFaceScan, initialFaceScanState);
  const [cameraPermission, requestCameraPermission] = useCameraPermissions();
  const summary = useMyPhotosSummary(tripId);
  const mutations = useMyPhotosMutations(tripId);
  const operation = useRef<AbortController | null>(null);
  const resumeOperation = useRef<AbortController | null>(null);
  const completionIdempotencyKeys = useRef(new Map<string, string>());
  const interruptionOperations = useRef(new Set<AbortController>());
  const locallyExpiredSessions = useRef(new Set<string>());
  const cooldownTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sessionExpiryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeTripId = useRef(tripId);
  const tripEpoch = useRef(0);
  const [startGate] = useState(() => new FaceScanStartGate(randomUUID));

  const clearCooldownTimer = useCallback(() => {
    if (cooldownTimer.current !== null) clearTimeout(cooldownTimer.current);
    cooldownTimer.current = null;
  }, []);
  const clearSessionExpiryTimer = useCallback(() => {
    if (sessionExpiryTimer.current !== null) clearTimeout(sessionExpiryTimer.current);
    sessionExpiryTimer.current = null;
  }, []);
  const reportFailure = useCallback((event: FailureEvent) => {
    clearCooldownTimer();
    dispatch(event);
    if (event.retryAfterSeconds) {
      cooldownTimer.current = setTimeout(() => {
        cooldownTimer.current = null;
        dispatch({ type: 'COOLDOWN_EXPIRED' });
        void summary.refetch();
      }, event.retryAfterSeconds * 1_000);
    }
  }, [clearCooldownTimer, summary]);

  const notifyServerOfInterruption = useCallback(async (
    sessionId: string,
    outcome: 'cancelled' | 'failed' | 'expired',
  ) => {
    if (!tripId) return;
    const controller = new AbortController();
    interruptionOperations.current.add(controller);
    try {
      await withMyPhotosContext(
        tripId,
        controller.signal,
        (context) => completeLivenessSession(
          context.tripId,
          sessionId,
          outcome,
          context.signal,
          (() => {
            const key = `${sessionId}:${outcome}`;
            const existing = completionIdempotencyKeys.current.get(key);
            if (existing) return existing;
            const created = randomUUID();
            completionIdempotencyKeys.current.set(key, created);
            return created;
          })(),
        ),
      );
    } catch {
      // Best effort only: the server's short, single-use expiry remains the
      // authoritative cleanup if the OS suspends networking immediately.
      recordMobileMetric('my_photos_enrollment_cancelled', 1, { outcome: 'failure' });
    } finally {
      interruptionOperations.current.delete(controller);
    }
  }, [tripId]);

  const completeSession = useCallback(async (
    sessionId: string,
    outcome: Exclude<NativeLivenessOutcome, 'unavailable'>,
  ) => {
    if (!tripId) return;
    clearSessionExpiryTimer();
    if (outcome === 'completed') dispatch({ type: 'NATIVE_COMPLETED' });
    const controller = new AbortController();
    operation.current?.abort();
    operation.current = controller;
    try {
      const result = await withMyPhotosContext(
        tripId,
        controller.signal,
        (context) => {
          const key = `${sessionId}:${outcome}`;
          let requestId = completionIdempotencyKeys.current.get(key);
          if (!requestId) {
            requestId = randomUUID();
            completionIdempotencyKeys.current.set(key, requestId);
          }
          return completeLivenessSession(
            context.tripId,
            sessionId,
            outcome,
            context.signal,
            requestId,
          );
        },
      );
      if (outcome === 'completed' && result.session_status === 'completed' && result.enrollment_status === 'enrolled') {
        dispatch({ type: 'VERIFIED' });
        await summary.refetch();
      } else {
        const reason = result.session_status === 'expired'
          ? 'session_expired'
          : result.session_status === 'cancelled'
            ? 'cancelled'
            : faceScanFailureFromStableCode(result.error_code) ?? 'liveness_rejected';
        const pendingCompletion = outcome === 'completed'
          && shouldReplayLivenessCompletionResult(result.error_code, result.retryable)
          ? { sessionId, outcome: 'completed' as const }
          : null;
        reportFailure({
          type: 'FAILED',
          reason,
          retryable: result.retryable,
          retryAfterSeconds: result.cooldown_until
            ? Math.max(1, Math.ceil((Date.parse(result.cooldown_until) - Date.now()) / 1_000))
            : null,
          ...(pendingCompletion ? { pendingCompletion } : {}),
        });
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        const event = faceScanFailureEventFromError(error);
        reportFailure(outcome === 'completed' && shouldReplayLivenessCompletion(error)
          ? {
              ...event,
              retryable: true,
              retryAfterSeconds: error instanceof ApiError && error.retryAfterSeconds !== null
                ? boundedCooldownSeconds(error.retryAfterSeconds)
                : event.retryAfterSeconds ?? null,
              pendingCompletion: { sessionId, outcome: 'completed' },
            }
          : event);
        if (error instanceof ApiError && error.status === 429) void summary.refetch();
      }
    } finally {
      if (operation.current === controller) operation.current = null;
    }
  }, [clearSessionExpiryTimer, reportFailure, summary, tripId]);

  const complete = useCallback((outcome: Exclude<NativeLivenessOutcome, 'unavailable'>) => (
    state.step === 'running' ? completeSession(state.sessionId, outcome) : Promise.resolve()
  ), [completeSession, state]);

  const retryPendingCompletion = useCallback(async (
    pending: Readonly<{ sessionId: string; outcome: 'completed' }>,
  ) => {
    if (operation.current) return;
    clearCooldownTimer();
    dispatch({ type: 'COMPLETION_RETRY_STARTED', sessionId: pending.sessionId });
    await completeSession(pending.sessionId, pending.outcome);
  }, [clearCooldownTimer, completeSession]);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (next) => {
      if (next === 'active') {
        if (state.step === 'failure' && state.pendingCompletion && !state.retryAfterSeconds) {
          const pending = state.pendingCompletion;
          const expectedTripId = tripId;
          const expectedTripEpoch = tripEpoch.current;
          const controller = new AbortController();
          resumeOperation.current?.abort(new Error('A newer Face Scan resume check started.'));
          resumeOperation.current = controller;
          void (async () => {
            try {
              const refreshed = await summary.refetch();
              if (
                controller.signal.aborted
                || activeTripId.current !== expectedTripId
                || tripEpoch.current !== expectedTripEpoch
              ) return;
              if (refreshed.data?.value.enrollment.status === 'enrolled') {
                dispatch({ type: 'COMPLETION_RETRY_STARTED', sessionId: pending.sessionId });
                dispatch({ type: 'VERIFIED' });
                return;
              }
              await retryPendingCompletion(pending);
            } catch {
              // The pending completion remains visible for an explicit retry.
              // A stale refetch must never publish into a later trip.
            } finally {
              if (resumeOperation.current === controller) resumeOperation.current = null;
            }
          })();
        }
        return;
      }
      resumeOperation.current?.abort(new Error('Face Scan resume checks pause in the background.'));
      if (state.step === 'starting' || state.step === 'running' || state.step === 'processing') {
        const sessionId = state.step === 'running' || state.step === 'processing'
          ? state.sessionId
          : null;
        clearSessionExpiryTimer();
        if (state.step === 'running') startGate.reset();
        operation.current?.abort();
        dispatch({ type: 'APP_BACKGROUNDED' });
        if (sessionId && state.step === 'running') {
          void notifyServerOfInterruption(
            sessionId,
            'cancelled',
          );
        }
      }
    });
    return () => subscription.remove();
  }, [clearSessionExpiryTimer, notifyServerOfInterruption, retryPendingCompletion, startGate, state, summary, tripId]);

  useLayoutEffect(() => {
    if (activeTripId.current === tripId) return;
    activeTripId.current = tripId;
    tripEpoch.current += 1;
    resumeOperation.current?.abort(new Error('The selected trip changed during Face Scan.'));
    resumeOperation.current = null;
    clearCooldownTimer();
    clearSessionExpiryTimer();
    operation.current?.abort(new Error('The selected trip changed during Face Scan.'));
    operation.current = null;
    for (const controller of interruptionOperations.current) {
      controller.abort(new Error('The selected trip changed during Face Scan.'));
    }
    interruptionOperations.current.clear();
    completionIdempotencyKeys.current.clear();
    locallyExpiredSessions.current.clear();
    startGate.reset();
    dispatch({ type: 'RESET' });
  }, [clearCooldownTimer, clearSessionExpiryTimer, startGate, tripId]);

  useEffect(() => () => {
    operation.current?.abort();
    resumeOperation.current?.abort();
    resumeOperation.current = null;
    for (const controller of interruptionOperations.current) controller.abort();
    interruptionOperations.current.clear();
    clearCooldownTimer();
    clearSessionExpiryTimer();
    locallyExpiredSessions.current.clear();
    startGate.reset();
  }, [clearCooldownTimer, clearSessionExpiryTimer, startGate]);

  const acceptConsent = useCallback(async () => {
    const consent = summary.data?.value.consent;
    if (!consent) return;
    try {
      await mutations.consent.mutateAsync(consent.required_version);
      dispatch({ type: 'CONSENT_ACCEPTED' });
    } catch (error) {
      reportFailure(faceScanFailureEventFromError(error));
    }
  }, [mutations.consent, reportFailure, summary.data?.value.consent]);

  const requestCamera = useCallback(async () => {
    try {
      const permission = cameraPermission?.granted ? cameraPermission : await requestCameraPermission();
      dispatch(permission.granted
        ? { type: 'CAMERA_GRANTED' }
        : { type: 'CAMERA_DENIED', canAskAgain: permission.canAskAgain });
    } catch (error) {
      reportFailure(faceScanFailureEventFromError(error));
    }
  }, [cameraPermission, reportFailure, requestCameraPermission]);

  const start = useCallback((): Promise<void> => {
    if (state.step !== 'ready' || !tripId) return Promise.resolve();
    const advertisedFlow = summary.data?.value.capability.client_flow;
    if (advertisedFlow === 'native' && !nativeBridge.available) {
      reportFailure({ type: 'FAILED', reason: 'device_unsupported' });
      return Promise.resolve();
    }
    if (advertisedFlow === 'unavailable') {
      reportFailure({ type: 'FAILED', reason: 'provider_unavailable' });
      return Promise.resolve();
    }
    return startGate.run(async (requestId) => {
      clearCooldownTimer();
      dispatch({ type: 'START' });
      const controller = new AbortController();
      operation.current?.abort();
      operation.current = controller;
      let sessionCreated = false;
      try {
        const session = await withMyPhotosContext(
          tripId,
          controller.signal,
          (context) => startLivenessSession(
            context.tripId,
            state.challengeMode,
            context.signal,
            requestId,
          ),
        );
        sessionCreated = true;
        dispatch({
          type: 'SESSION_CREATED',
          clientFlow: session.client_flow,
          sessionId: session.session_id,
          expiresAt: session.expires_at,
        });
        const expiryDelay = Math.min(
          MAX_LIVENESS_SESSION_LIFETIME_MS,
          Math.max(0, Date.parse(session.expires_at) - Date.now()),
        );
        clearSessionExpiryTimer();
        sessionExpiryTimer.current = setTimeout(() => {
          sessionExpiryTimer.current = null;
          locallyExpiredSessions.current.add(session.session_id);
          operation.current?.abort();
          void completeSession(session.session_id, 'expired');
        }, expiryDelay);
        if (session.client_flow === 'native') {
          if (!nativeBridge.available) {
            clearSessionExpiryTimer();
            reportFailure({ type: 'FAILED', reason: 'device_unsupported' });
            void notifyServerOfInterruption(session.session_id, 'cancelled');
            return 'clear_idempotency_key';
          }
          const providerSessionId = session.native_launch_handle;
          if (!providerSessionId) throw new Error('Native Face Scan launch material was not provided.');
          const outcome = await nativeBridge.present({
            providerSessionId,
            expiresAt: session.expires_at,
          }, controller.signal);
          // The local deadline aborts the native bridge to dismiss camera UI.
          // Suppress its derived "cancelled" result because the timer already
          // submitted the authoritative expired outcome exactly once.
          if (locallyExpiredSessions.current.delete(session.session_id)) {
            return 'clear_idempotency_key';
          }
          // Background, manual-cancel, trip-switch and unmount boundaries abort
          // this controller and own any required server cleanup. Never let the
          // native bridge's derived cancelled result publish into a later trip.
          if (controller.signal.aborted) return 'clear_idempotency_key';
          if (outcome === 'unavailable') {
            clearSessionExpiryTimer();
            reportFailure({ type: 'FAILED', reason: 'device_unsupported' });
            void notifyServerOfInterruption(session.session_id, 'cancelled');
          }
          else await completeSession(session.session_id, outcome);
        } else {
          assertDevelopmentLivenessSimulatorAllowed(session);
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          const event = faceScanFailureEventFromError(error);
          reportFailure(event);
          if (error instanceof ApiError && error.status === 429) void summary.refetch();
        }
        return faceScanStartDisposition({
          sessionCreated,
          operationAborted: controller.signal.aborted,
          transportAmbiguous: shouldRetainFaceScanStartIdempotencyKey(error),
        });
      } finally {
        if (operation.current === controller) operation.current = null;
      }
      return 'clear_idempotency_key';
    });
  }, [
    clearCooldownTimer,
    clearSessionExpiryTimer,
    completeSession,
    nativeBridge,
    notifyServerOfInterruption,
    reportFailure,
    state,
    startGate,
    summary,
    tripId,
  ]);

  const simulate = useCallback((outcome: 'completed' | 'cancelled' | 'expired' | 'failed') => {
    if (state.step !== 'running') return Promise.resolve();
    const session = summary.data?.value.capability.client_flow;
    if (session !== 'development_simulator') {
      reportFailure({ type: 'FAILED', reason: 'nonrecoverable', retryable: false });
      return Promise.resolve();
    }
    return complete(outcome).catch(() => {
      reportFailure({ type: 'FAILED', reason: failureFromOutcome(outcome) });
    });
  }, [complete, reportFailure, state.step, summary.data?.value.capability.client_flow]);

  const chooseChallenge = useCallback((mode: z.infer<typeof ChallengeModeSchema>) => {
    dispatch({ type: mode === 'movement_only' ? 'USE_MOVEMENT_ONLY' : 'USE_MOVEMENT_AND_LIGHT' });
  }, []);

  const cancel = useCallback(() => {
    clearSessionExpiryTimer();
    if (state.step === 'running') startGate.reset();
    const sessionId = state.step === 'running' ? state.sessionId : null;
    operation.current?.abort();
    dispatch({ type: 'CANCEL' });
    if (sessionId) void notifyServerOfInterruption(sessionId, 'cancelled');
  }, [clearSessionExpiryTimer, notifyServerOfInterruption, startGate, state]);

  return {
    state,
    summary,
    cameraPermission,
    continueExplanation: () => {
      dispatch({ type: 'CONTINUE' });
      if (summary.data?.value.consent.required === false) dispatch({ type: 'CONSENT_ACCEPTED' });
    },
    acceptConsent,
    chooseChallenge,
    continuePreparation: () => dispatch({ type: 'CONTINUE' }),
    requestCamera,
    start,
    simulate,
    cancel,
    retry: () => {
      if (state.step === 'failure' && state.pendingCompletion && !state.retryAfterSeconds) {
        void retryPendingCompletion(state.pendingCompletion);
      } else {
        dispatch({ type: 'RETRY' });
      }
    },
    cooldownExpired: () => dispatch({ type: 'COOLDOWN_EXPIRED' }),
    cameraUnavailable: (frontOnly = false) => reportFailure({
      type: 'FAILED',
      reason: frontOnly ? 'front_camera_unavailable' : 'camera_unavailable',
    }),
  } as const;
}
