import { act, renderHook, waitFor } from '@testing-library/react-native';
import { useCameraPermissions } from 'expo-camera';
import { randomUUID } from 'expo-crypto';
import { AppState, type AppStateStatus } from 'react-native';

import { ApiError } from '@/core/api/client';
import { recordMobileMetric } from '@/core/observability/mobile-observability';

import {
  completeLivenessSession,
  startLivenessSession,
} from '../../api/my-photos-api';
import { withMyPhotosContext } from '../../data/my-photos-context';
import type { NativeFaceLivenessBridge } from '../../liveness/liveness-client';
import { assertDevelopmentLivenessSimulatorAllowed } from '../../liveness/liveness-client';
import {
  faceScanFailureEventFromError,
  shouldRetainFaceScanStartIdempotencyKey,
  useFaceScanController,
} from '../use-face-scan-controller';
import { useMyPhotosMutations, useMyPhotosSummary } from '../use-my-photos';

jest.mock('expo-camera', () => ({ useCameraPermissions: jest.fn() }));
jest.mock('expo-crypto', () => ({ randomUUID: jest.fn() }));
jest.mock('@/core/observability/mobile-observability', () => ({
  recordMobileMetric: jest.fn(),
}));
jest.mock('../../api/my-photos-api', () => ({
  completeLivenessSession: jest.fn(),
  startLivenessSession: jest.fn(),
}));
jest.mock('../../data/my-photos-context', () => ({
  withMyPhotosContext: jest.fn(),
}));
jest.mock('../../liveness/liveness-client', () => ({
  assertDevelopmentLivenessSimulatorAllowed: jest.fn(),
  nativeFaceLivenessBridge: Object.freeze({
    available: false,
    present: jest.fn(async () => 'unavailable'),
  }),
}));
jest.mock('../use-my-photos', () => ({
  useMyPhotosMutations: jest.fn(),
  useMyPhotosSummary: jest.fn(),
}));

const TRIP_ID = '11111111-1111-4111-8111-111111111111';
const SECOND_TRIP_ID = '55555555-5555-4555-8555-555555555555';
const PASSENGER_ID = '22222222-2222-4222-8222-222222222222';
const SESSION_ID = '33333333-3333-4333-8333-333333333333';
const SEARCH_ID = '44444444-4444-4444-8444-444444444444';
const START_KEY = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const COMPLETION_KEY = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

const requestCameraPermission = jest.fn();
const consentMutation = jest.fn();
const refetchSummary = jest.fn();

const mockedUseCameraPermissions = jest.mocked(useCameraPermissions);
const mockedRandomUuid = jest.mocked(randomUUID);
const mockedStartLivenessSession = jest.mocked(startLivenessSession);
const mockedCompleteLivenessSession = jest.mocked(completeLivenessSession);
const mockedWithContext = jest.mocked(withMyPhotosContext);
const mockedUseSummary = jest.mocked(useMyPhotosSummary);
const mockedUseMutations = jest.mocked(useMyPhotosMutations);
const mockedSimulatorGuard = jest.mocked(assertDevelopmentLivenessSimulatorAllowed);
const mockedMetric = jest.mocked(recordMobileMetric);

type AdvertisedFlow = 'development_simulator' | 'native' | 'unavailable';

function summaryValue(flow: AdvertisedFlow, consentRequired = true) {
  return {
    data: {
      value: {
        consent: {
          required: consentRequired,
          required_version: 'my-photos-biometric-v1',
        },
        capability: { client_flow: flow },
        enrollment: { status: 'not_enrolled' },
      },
      source: 'network',
    },
    refetch: refetchSummary,
  };
}

function livenessSession(
  flow: Exclude<AdvertisedFlow, 'unavailable'>,
  challengeMode: 'movement_and_light' | 'movement_only' = 'movement_and_light',
) {
  return {
    session_id: SESSION_ID,
    status: 'created',
    challenge_mode: challengeMode,
    client_flow: flow,
    native_launch_handle: flow === 'native' ? 'opaque-native-launch-handle' : null,
    expires_at: '2099-08-23T10:05:00.000Z',
    attempts_remaining: 2,
    photosensitivity_warning: 'The light challenge may affect photosensitive passengers.',
  } as const;
}

function successfulCompletion() {
  return {
    session_id: SESSION_ID,
    session_status: 'completed',
    enrollment_status: 'enrolled',
    search_run_id: SEARCH_ID,
    search_status: 'queued',
    retryable: false,
    error_code: null,
    cooldown_until: null,
  } as const;
}

async function moveToReady(
  result: Readonly<{ current: ReturnType<typeof useFaceScanController> }>,
  challengeMode: 'movement_and_light' | 'movement_only' = 'movement_and_light',
) {
  await act(() => result.current.continueExplanation());
  expect(result.current.state.step).toBe('consent');
  await act(async () => result.current.acceptConsent());
  expect(result.current.state.step).toBe('preparation');
  await act(() => result.current.chooseChallenge(challengeMode));
  await act(() => result.current.continuePreparation());
  expect(result.current.state.step).toBe('camera_permission');
  await act(async () => result.current.requestCamera());
  expect(result.current.state.step).toBe('ready');
}

let appStateListener: ((status: AppStateStatus) => void) | null = null;

beforeEach(() => {
  jest.clearAllMocks();
  appStateListener = null;
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, listener) => {
    appStateListener = listener;
    return { remove: jest.fn() };
  });
  mockedRandomUuid
    .mockReturnValueOnce(START_KEY)
    .mockReturnValue(COMPLETION_KEY);
  mockedUseCameraPermissions.mockReturnValue([
    { granted: false, canAskAgain: true } as never,
    requestCameraPermission,
    jest.fn(),
  ]);
  requestCameraPermission.mockResolvedValue({ granted: true, canAskAgain: true });
  consentMutation.mockResolvedValue(undefined);
  refetchSummary.mockResolvedValue({ data: summaryValue('development_simulator').data });
  mockedUseSummary.mockReturnValue(summaryValue('development_simulator') as never);
  mockedUseMutations.mockReturnValue({
    consent: { mutateAsync: consentMutation },
  } as never);
  mockedWithContext.mockImplementation(async (tripId, signal, operation) => operation({
    namespace: 'tenant.account',
    sessionId: 'signed-in-session',
    agencyId: 'tenant',
    principalId: 'account',
    role: 'passenger',
    tripId,
    passengerId: PASSENGER_ID,
    signal,
  }, jest.fn()) as never);
  mockedStartLivenessSession.mockResolvedValue(livenessSession('development_simulator'));
  mockedCompleteLivenessSession.mockResolvedValue(successfulCompletion());
});

afterEach(() => {
  jest.restoreAllMocks();
  jest.useRealTimers();
});

describe('Face Scan controller lifecycle', () => {
  test('drives consent, camera permission, simulator enrollment, and authoritative verification', async () => {
    mockedStartLivenessSession.mockResolvedValue(
      livenessSession('development_simulator', 'movement_only'),
    );
    const { result, unmount } = await renderHook(() => useFaceScanController(TRIP_ID));

    await moveToReady(result, 'movement_only');
    await act(async () => result.current.start());

    expect(result.current.state).toMatchObject({
      step: 'running',
      clientFlow: 'development_simulator',
      sessionId: SESSION_ID,
    });
    expect(consentMutation).toHaveBeenCalledWith('my-photos-biometric-v1');
    expect(mockedStartLivenessSession).toHaveBeenCalledWith(
      TRIP_ID,
      'movement_only',
      expect.any(AbortSignal),
      START_KEY,
    );
    expect(mockedSimulatorGuard).toHaveBeenCalledWith(
      livenessSession('development_simulator', 'movement_only'),
    );

    await act(async () => result.current.simulate('completed'));

    expect(result.current.state).toEqual({ step: 'success' });
    expect(mockedCompleteLivenessSession).toHaveBeenCalledWith(
      TRIP_ID,
      SESSION_ID,
      'completed',
      expect.any(AbortSignal),
      COMPLETION_KEY,
    );
    expect(refetchSummary).toHaveBeenCalledTimes(1);
    await act(() => unmount());
  });

  test('passes only an opaque launch handle to the native lifecycle bridge', async () => {
    mockedUseSummary.mockReturnValue(summaryValue('native') as never);
    mockedStartLivenessSession.mockResolvedValue(livenessSession('native'));
    const bridge: NativeFaceLivenessBridge = {
      available: true,
      present: jest.fn(async () => 'completed'),
    };
    const { result, unmount } = await renderHook(() => useFaceScanController(TRIP_ID, bridge));

    await moveToReady(result);
    await act(async () => result.current.start());

    expect(bridge.present).toHaveBeenCalledWith({
      providerSessionId: 'opaque-native-launch-handle',
      expiresAt: '2099-08-23T10:05:00.000Z',
    }, expect.any(AbortSignal));
    expect(result.current.state).toEqual({ step: 'success' });
    expect(mockedSimulatorGuard).not.toHaveBeenCalled();
    await act(() => unmount());
  });

  test('hard-expires native camera work once and suppresses its abort-derived cancelled outcome', async () => {
    jest.useFakeTimers();
    mockedUseSummary.mockReturnValue(summaryValue('native') as never);
    mockedStartLivenessSession.mockResolvedValue(livenessSession('native'));
    mockedCompleteLivenessSession.mockResolvedValue({
      session_id: SESSION_ID,
      session_status: 'expired',
      enrollment_status: 'ready',
      search_run_id: null,
      search_status: 'not_started',
      retryable: true,
      error_code: 'SESSION_EXPIRED',
      cooldown_until: null,
    });
    const bridge: NativeFaceLivenessBridge = {
      available: true,
      present: jest.fn((_request, signal) => new Promise((resolve) => {
        signal?.addEventListener('abort', () => resolve('cancelled'), { once: true });
      })),
    };
    const { result, unmount } = await renderHook(() => useFaceScanController(TRIP_ID, bridge));

    await moveToReady(result);
    let startPromise: Promise<void> | undefined;
    await act(async () => {
      startPromise = result.current.start();
      for (let index = 0; index < 6; index += 1) await Promise.resolve();
    });
    expect(result.current.state).toMatchObject({ step: 'running', sessionId: SESSION_ID });

    await act(async () => {
      jest.advanceTimersByTime(3 * 60_000);
      await startPromise;
      for (let index = 0; index < 6; index += 1) await Promise.resolve();
    });

    expect(mockedCompleteLivenessSession).toHaveBeenCalledTimes(1);
    expect(mockedCompleteLivenessSession).toHaveBeenCalledWith(
      TRIP_ID,
      SESSION_ID,
      'expired',
      expect.any(AbortSignal),
      COMPLETION_KEY,
    );
    expect(mockedCompleteLivenessSession).not.toHaveBeenCalledWith(
      TRIP_ID,
      SESSION_ID,
      'cancelled',
      expect.anything(),
      expect.anything(),
    );
    expect(result.current.state).toMatchObject({ step: 'failure', reason: 'session_expired' });
    await act(() => unmount());
  });

  test('hard-resets and aborts native Face Scan when the selected trip changes', async () => {
    jest.useFakeTimers();
    mockedUseSummary.mockReturnValue(summaryValue('native') as never);
    mockedStartLivenessSession.mockResolvedValue(livenessSession('native'));
    let nativeSignal: AbortSignal | undefined;
    const bridge: NativeFaceLivenessBridge = {
      available: true,
      present: jest.fn((_request, signal) => new Promise((resolve) => {
        nativeSignal = signal;
        signal?.addEventListener('abort', () => resolve('cancelled'), { once: true });
      })),
    };
    const { result, rerender, unmount } = await renderHook(
      ({ tripId }: { tripId: string }) => useFaceScanController(tripId, bridge),
      { initialProps: { tripId: TRIP_ID } },
    );

    await moveToReady(result);
    let startPromise: Promise<void> | undefined;
    await act(async () => {
      startPromise = result.current.start();
      for (let index = 0; index < 6; index += 1) await Promise.resolve();
    });
    expect(result.current.state).toMatchObject({ step: 'running', sessionId: SESSION_ID });

    await act(() => rerender({ tripId: SECOND_TRIP_ID }));
    await act(async () => {
      await startPromise;
      for (let index = 0; index < 6; index += 1) await Promise.resolve();
    });

    expect(nativeSignal?.aborted).toBe(true);
    expect(result.current.state).toEqual({ step: 'explanation' });
    expect(mockedCompleteLivenessSession).not.toHaveBeenCalled();
    await act(async () => {
      jest.advanceTimersByTime(3 * 60_000);
      for (let index = 0; index < 3; index += 1) await Promise.resolve();
    });
    expect(mockedCompleteLivenessSession).not.toHaveBeenCalled();
    await act(() => unmount());
  });

  test('clears an old-trip cooldown without refetching it after the trip changes', async () => {
    jest.useFakeTimers();
    mockedStartLivenessSession.mockRejectedValue(
      new ApiError('Slow down.', 429, 'MY_PHOTOS_PROVIDER_THROTTLED', 30),
    );
    const { result, rerender, unmount } = await renderHook(
      ({ tripId }: { tripId: string }) => useFaceScanController(tripId),
      { initialProps: { tripId: TRIP_ID } },
    );

    await moveToReady(result);
    await act(async () => result.current.start());
    expect(result.current.state).toMatchObject({
      step: 'failure',
      reason: 'rate_limited',
      retryAfterSeconds: 30,
    });
    expect(refetchSummary).toHaveBeenCalledTimes(1);

    await act(() => rerender({ tripId: SECOND_TRIP_ID }));
    expect(result.current.state).toEqual({ step: 'explanation' });
    await act(async () => {
      jest.advanceTimersByTime(30_000);
      for (let index = 0; index < 3; index += 1) await Promise.resolve();
    });
    expect(refetchSummary).toHaveBeenCalledTimes(1);
    await act(() => unmount());
  });

  test('does not replay a pending completion after its resume refetch crosses a trip switch', async () => {
    mockedCompleteLivenessSession.mockRejectedValueOnce(
      new ApiError('Connection ended after submission.', 0, 'NETWORK_ERROR', null),
    );
    const { result, rerender, unmount } = await renderHook(
      ({ tripId }: { tripId: string }) => useFaceScanController(tripId),
      { initialProps: { tripId: TRIP_ID } },
    );

    await moveToReady(result);
    await act(async () => result.current.start());
    await act(async () => result.current.simulate('completed'));
    expect(result.current.state).toMatchObject({
      step: 'failure',
      pendingCompletion: { sessionId: SESSION_ID, outcome: 'completed' },
    });

    let resolveRefetch!: (value: { data: ReturnType<typeof summaryValue>['data'] }) => void;
    refetchSummary.mockImplementationOnce(() => new Promise((resolve) => {
      resolveRefetch = resolve;
    }));
    await act(() => appStateListener?.('active'));
    expect(refetchSummary).toHaveBeenCalledTimes(1);

    await act(() => rerender({ tripId: SECOND_TRIP_ID }));
    await act(async () => {
      resolveRefetch({ data: summaryValue('development_simulator').data });
      for (let index = 0; index < 6; index += 1) await Promise.resolve();
    });

    expect(result.current.state).toEqual({ step: 'explanation' });
    expect(mockedCompleteLivenessSession).toHaveBeenCalledTimes(1);
    await act(() => unmount());
  });

  test('replays an ambiguous completion with the same session and idempotency key', async () => {
    mockedCompleteLivenessSession
      .mockRejectedValueOnce(new ApiError('Connection ended after submission.', 0, 'NETWORK_ERROR', null))
      .mockResolvedValueOnce(successfulCompletion());
    const { result, unmount } = await renderHook(() => useFaceScanController(TRIP_ID));

    await moveToReady(result);
    await act(async () => result.current.start());
    await act(async () => result.current.simulate('completed'));

    expect(result.current.state).toMatchObject({
      step: 'failure',
      reason: 'network_interrupted',
      pendingCompletion: { sessionId: SESSION_ID, outcome: 'completed' },
    });

    await act(async () => result.current.retry());
    await waitFor(() => expect(result.current.state).toEqual({ step: 'success' }));

    expect(mockedCompleteLivenessSession).toHaveBeenCalledTimes(2);
    expect(mockedCompleteLivenessSession.mock.calls[0]?.[4]).toBe(COMPLETION_KEY);
    expect(mockedCompleteLivenessSession.mock.calls[1]?.[4]).toBe(COMPLETION_KEY);
    expect(mockedStartLivenessSession).toHaveBeenCalledTimes(1);
    await act(() => unmount());
  });

  test('fails closed when native capability is advertised but unavailable', async () => {
    mockedUseSummary.mockReturnValue(summaryValue('native') as never);
    const { result, unmount } = await renderHook(() => useFaceScanController(TRIP_ID));

    await moveToReady(result);
    await act(async () => result.current.start());

    expect(result.current.state).toMatchObject({
      step: 'failure',
      reason: 'device_unsupported',
      retryable: false,
    });
    expect(mockedStartLivenessSession).not.toHaveBeenCalled();
    await act(() => unmount());
  });

  test('cancels a running single-use session when the app backgrounds', async () => {
    const { result, unmount } = await renderHook(() => useFaceScanController(TRIP_ID));

    await moveToReady(result);
    await act(async () => result.current.start());
    await act(async () => appStateListener?.('background'));

    expect(result.current.state).toMatchObject({
      step: 'failure',
      reason: 'backgrounded',
    });
    await waitFor(() => expect(mockedCompleteLivenessSession).toHaveBeenCalledWith(
      TRIP_ID,
      SESSION_ID,
      'cancelled',
      expect.any(AbortSignal),
      expect.stringMatching(/^[0-9a-f-]{36}$/i),
    ));
    await act(() => unmount());
  });

  test('maps stable transport/provider failures and bounds server cooldowns', () => {
    expect(faceScanFailureEventFromError(
      new ApiError('Slow down.', 429, 'MY_PHOTOS_PROVIDER_THROTTLED', 99_999),
    )).toEqual({
      type: 'FAILED',
      reason: 'rate_limited',
      retryable: true,
      retryAfterSeconds: 3_600,
    });
    expect(faceScanFailureEventFromError(
      new ApiError('Provider failed.', 503, 'UNEXPECTED_PROVIDER_FAILURE', null),
    )).toEqual({ type: 'FAILED', reason: 'provider_unavailable' });
    expect(faceScanFailureEventFromError(new TypeError('Network unavailable.')))
      .toEqual({ type: 'FAILED', reason: 'network_interrupted' });
    expect(faceScanFailureEventFromError(new Error('Unexpected response.')))
      .toEqual({ type: 'FAILED', reason: 'nonrecoverable' });
    expect(shouldRetainFaceScanStartIdempotencyKey(
      new ApiError('Timed out.', 408, 'REQUEST_TIMEOUT', null),
    )).toBe(true);
    expect(shouldRetainFaceScanStartIdempotencyKey(
      new ApiError('No face.', 422, 'MY_PHOTOS_NO_FACE', null),
    )).toBe(false);
    expect(mockedMetric).not.toHaveBeenCalled();
  });
});
