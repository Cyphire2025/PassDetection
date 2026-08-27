import { env } from '@/core/config/env';
import { NativeModules, Platform } from 'react-native';

import type { LivenessSession } from '../api/contracts';

export type NativeLivenessOutcome =
  | 'completed'
  | 'cancelled'
  | 'expired'
  | 'failed'
  | 'unavailable';

export type NativeLivenessRequest = Readonly<{
  /** Short-lived provider session identifier returned by the backend. It is
   * never a credential and must not be logged or persisted. */
  providerSessionId: string;
  expiresAt: string;
}>;

/** Narrow lifecycle-only boundary for the official native component.
 * Frames, video, credentials, provider responses and confidence never cross JS. */
export interface NativeFaceLivenessBridge {
  readonly available: boolean;
  readonly region?: string;
  present(request: NativeLivenessRequest, signal?: AbortSignal): Promise<NativeLivenessOutcome>;
}

type AndroidFaceLivenessModule = Readonly<{
  available?: unknown;
  provider?: unknown;
  region?: unknown;
  present?: (providerSessionId: string, expiresAt: string) => Promise<unknown>;
  cancel?: () => Promise<unknown>;
}>;

const NATIVE_OUTCOMES = new Set<NativeLivenessOutcome>([
  'completed', 'cancelled', 'expired', 'failed', 'unavailable',
]);
const PROVIDER_SESSION_PATTERN = /^[A-Za-z0-9._:-]+$/;
const AWS_REGION_PATTERN = /^[a-z]{2}(?:-gov)?-[a-z]+-\d$/;

export function createAndroidFaceLivenessBridge(input: Readonly<{
  platform: string;
  module: AndroidFaceLivenessModule | null | undefined;
}>): NativeFaceLivenessBridge {
  const module = input.module;
  const region = typeof module?.region === 'string' && AWS_REGION_PATTERN.test(module.region)
    ? module.region
    : undefined;
  const available = input.platform === 'android'
    && module?.available === true
    && module.provider === 'cognito_identity_pool'
    && Boolean(region)
    && typeof module.present === 'function'
    && typeof module.cancel === 'function';

  return Object.freeze({
    available,
    ...(region ? { region } : {}),
    async present(
      request: NativeLivenessRequest,
      signal?: AbortSignal,
    ): Promise<NativeLivenessOutcome> {
      const nativePresent = module?.present;
      const nativeCancel = module?.cancel;
      if (!available || !nativePresent || !nativeCancel) return 'unavailable';
      if (
        request.providerSessionId.length < 1
        || request.providerSessionId.length > 512
        || !PROVIDER_SESSION_PATTERN.test(request.providerSessionId)
      ) return 'failed';
      const expiresAt = Date.parse(request.expiresAt);
      const lifetime = expiresAt - Date.now();
      // Rekognition Face Liveness sessions have a hard three-minute lifetime.
      if (!Number.isFinite(expiresAt) || lifetime <= 0 || lifetime > 3 * 60_000) return 'expired';
      if (signal?.aborted) return 'cancelled';

      return new Promise<NativeLivenessOutcome>((resolve) => {
        let settled = false;
        const finish = (outcome: NativeLivenessOutcome) => {
          if (settled) return;
          settled = true;
          signal?.removeEventListener('abort', cancel);
          resolve(outcome);
        };
        const cancel = () => {
          void nativeCancel().catch(() => undefined);
          finish('cancelled');
        };
        signal?.addEventListener('abort', cancel, { once: true });
        void nativePresent(request.providerSessionId, request.expiresAt).then(
          (outcome) => finish(
            typeof outcome === 'string' && NATIVE_OUTCOMES.has(outcome as NativeLivenessOutcome)
              ? outcome as NativeLivenessOutcome
              : 'failed',
          ),
          () => finish('failed'),
        );
      });
    },
  });
}

export const unavailableNativeFaceLivenessBridge: NativeFaceLivenessBridge = Object.freeze({
  available: false,
  present: async (): Promise<NativeLivenessOutcome> => 'unavailable',
});

export const nativeFaceLivenessBridge = createAndroidFaceLivenessBridge({
  platform: Platform.OS,
  module: NativeModules.GCFaceLiveness as AndroidFaceLivenessModule | undefined,
});

export function developmentLivenessSimulatorPolicy(input: Readonly<{
  appEnv: 'development' | 'preview' | 'production';
  apiHostname: string;
  clientFlow: LivenessSession['client_flow'];
}>): boolean {
  return input.clientFlow === 'development_simulator'
    && input.appEnv === 'development'
    && ['localhost', '127.0.0.1', '10.0.2.2'].includes(input.apiHostname);
}

export function developmentLivenessSimulatorAllowed(session: LivenessSession): boolean {
  return developmentLivenessSimulatorPolicy({
    appEnv: env.appEnv,
    apiHostname: new URL(env.apiUrl).hostname,
    clientFlow: session.client_flow,
  });
}

export function assertDevelopmentLivenessSimulatorAllowed(session: LivenessSession): void {
  if (!developmentLivenessSimulatorAllowed(session)) {
    throw new Error('Development Face Scan simulation is unavailable in this build or environment.');
  }
}
