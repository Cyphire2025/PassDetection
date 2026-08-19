import * as AppIntegrity from '@expo/app-integrity';
import * as Crypto from 'expo-crypto';
import { Platform } from 'react-native';

import {
  MobileAppAttestRegistrationResponseSchema,
  MobileIntegrityChallengeResponseSchema,
} from '@/core/api/contracts';
import { ApiError, apiRequest } from '@/core/api/client';
import { env } from '@/core/config/env';
import {
  clearAppAttestKeyRecord,
  getAppAttestKeyRecord,
  getInstallationId,
  setAppAttestKeyRecord,
} from '@/core/storage/secure-store';

export type MobileIntegrityProofBody = Readonly<{
  challenge_id: string;
  provider: 'play_integrity' | 'app_attest';
  proof: string;
  installation_id: string;
  key_id?: string;
}>;

type DocumentIntegrityInput = Readonly<{
  namespace: string;
  tripId: string;
  documentId: string;
  version: number;
}>;

let playProviderPreparation: Promise<void> | null = null;

export class AppIntegrityUnsupportedError extends Error {
  readonly code = 'APP_INTEGRITY_UNSUPPORTED';

  constructor() {
    super('This device cannot verify the app for this protected action.');
    this.name = 'AppIntegrityUnsupportedError';
  }
}

export async function createDocumentAuthorizationIntegrityProof(
  input: DocumentIntegrityInput,
  signal?: AbortSignal,
): Promise<MobileIntegrityProofBody | undefined> {
  if (env.appIntegrityMode === 'disabled') return undefined;
  assertActive(signal);
  const installationId = await getInstallationId();
  const requestHash = await sha256Base64Url(
    `gc-mobile-integrity-v1\0document_download_authorize\0${input.tripId}\0${input.documentId}\0${input.version}`,
  );
  try {
    if (Platform.OS === 'android') {
      return await createPlayIntegrityProof(requestHash, installationId, signal);
    }
    if (Platform.OS === 'ios') {
      return await createAppAttestProof(input.namespace, requestHash, installationId, signal);
    }
    throw new AppIntegrityUnsupportedError();
  } catch (error) {
    if (signal?.aborted) throw error;
    if (env.appIntegrityMode === 'monitor') return undefined;
    throw error;
  }
}

async function createPlayIntegrityProof(
  requestHash: string,
  installationId: string,
  signal?: AbortSignal,
): Promise<MobileIntegrityProofBody | undefined> {
  const challenge = await requestChallenge({
    provider: 'play_integrity',
    action: 'document_download_authorize',
    request_hash: requestHash,
    installation_id: installationId,
  }, signal);
  if (!challenge) return undefined;
  await preparePlayIntegrityProvider();
  assertActive(signal);
  let proof: string;
  try {
    proof = await AppIntegrity.requestIntegrityCheckAsync(challenge.providerRequestHash);
  } catch (error) {
    if (integrityErrorCode(error) !== 'ERR_APP_INTEGRITY_PROVIDER_INVALID') throw error;
    playProviderPreparation = null;
    await preparePlayIntegrityProvider();
    assertActive(signal);
    proof = await AppIntegrity.requestIntegrityCheckAsync(challenge.providerRequestHash);
  }
  assertProof(proof);
  assertActive(signal);
  return {
    challenge_id: challenge.challengeId,
    provider: 'play_integrity',
    proof,
    installation_id: installationId,
  };
}

async function createAppAttestProof(
  namespace: string,
  requestHash: string,
  installationId: string,
  signal?: AbortSignal,
): Promise<MobileIntegrityProofBody | undefined> {
  if (!AppIntegrity.isSupported) throw new AppIntegrityUnsupportedError();
  const keyId = await ensureRegisteredAppAttestKey(namespace, installationId, signal);
  if (!keyId) return undefined;
  const challenge = await requestChallenge({
    provider: 'app_attest',
    action: 'document_download_authorize',
    request_hash: requestHash,
    installation_id: installationId,
    key_id: keyId,
  }, signal);
  if (!challenge) return undefined;
  assertActive(signal);
  const proof = await AppIntegrity.generateAssertionAsync(
    keyId,
    challenge.providerRequestHash,
  );
  assertProof(proof);
  assertActive(signal);
  return {
    challenge_id: challenge.challengeId,
    provider: 'app_attest',
    proof,
    installation_id: installationId,
    key_id: keyId,
  };
}

async function ensureRegisteredAppAttestKey(
  namespace: string,
  installationId: string,
  signal?: AbortSignal,
): Promise<string | null> {
  const existing = await getAppAttestKeyRecord(namespace);
  if (existing?.registered) return existing.keyId;
  const keyId = existing?.keyId ?? await AppIntegrity.generateKeyAsync();
  if (!existing) {
    await setAppAttestKeyRecord(namespace, {
      formatVersion: 1,
      keyId,
      registered: false,
    });
  }
  const requestHash = await sha256Base64Url(
    `gc-mobile-integrity-v1\0app_attest_key_register\0${keyId}`,
  );
  const challenge = await requestChallenge({
    provider: 'app_attest',
    action: 'app_attest_key_register',
    request_hash: requestHash,
    installation_id: installationId,
    key_id: keyId,
  }, signal);
  if (!challenge) return null;
  try {
    assertActive(signal);
    const attestationObject = await AppIntegrity.attestKeyAsync(
      keyId,
      challenge.providerRequestHash,
    );
    assertProof(attestationObject);
    await apiRequest('/mobile/integrity/app-attest/keys/register', {
      method: 'POST',
      body: {
        challenge_id: challenge.challengeId,
        installation_id: installationId,
        key_id: keyId,
        attestation_object: attestationObject,
      },
      schema: MobileAppAttestRegistrationResponseSchema,
      timeoutMs: 15_000,
      ...(signal ? { signal } : {}),
    });
    await setAppAttestKeyRecord(namespace, {
      formatVersion: 1,
      keyId,
      registered: true,
    });
    return keyId;
  } catch (error) {
    // Apple explicitly permits retrying the same key when its service is
    // unavailable. Other native attestation failures require a fresh key.
    const nativeErrorCode = integrityErrorCode(error);
    const isRetryableOutage = nativeErrorCode === 'ERR_APP_INTEGRITY_SERVER_UNAVAILABLE'
      || (error instanceof ApiError && error.status >= 500);
    if (!isRetryableOutage) {
      await clearAppAttestKeyRecord(namespace).catch(() => undefined);
    }
    throw error;
  }
}

async function requestChallenge(
  body: Readonly<{
    provider: 'play_integrity' | 'app_attest';
    action: 'document_download_authorize' | 'app_attest_key_register';
    request_hash: string;
    installation_id: string;
    key_id?: string;
  }>,
  signal?: AbortSignal,
): Promise<Readonly<{ challengeId: string; providerRequestHash: string }> | null> {
  const response = await apiRequest('/mobile/integrity/challenges', {
    method: 'POST',
    body,
    schema: MobileIntegrityChallengeResponseSchema,
    timeoutMs: 10_000,
    ...(signal ? { signal } : {}),
  });
  if (response.status === 'disabled') return null;
  if (
    response.challenge_id === null
    || response.provider_request_hash === null
    || response.expires_at === null
    || Date.parse(response.expires_at) <= Date.now()
    || response.provider !== body.provider
  ) {
    throw new Error('The server returned an invalid app-integrity challenge.');
  }
  return {
    challengeId: response.challenge_id,
    providerRequestHash: response.provider_request_hash,
  };
}

function preparePlayIntegrityProvider(): Promise<void> {
  const cloudProjectNumber = env.playIntegrityCloudProjectNumber;
  if (!cloudProjectNumber) throw new AppIntegrityUnsupportedError();
  playProviderPreparation ??= AppIntegrity.prepareIntegrityTokenProviderAsync(
    cloudProjectNumber,
  ).catch((error: unknown) => {
    playProviderPreparation = null;
    throw error;
  });
  return playProviderPreparation;
}

async function sha256Base64Url(value: string): Promise<string> {
  const digest = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    value,
    { encoding: Crypto.CryptoEncoding.BASE64 },
  );
  return digest.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function assertProof(value: string): void {
  // Play Integrity tokens and App Attest payloads are ASCII encodings, so
  // JavaScript string length is also their network byte length.
  const byteLength = value.length;
  if (byteLength < 16 || byteLength > 65_536) {
    throw new Error('The platform returned an invalid app-integrity proof.');
  }
}

function assertActive(signal?: AbortSignal): void {
  if (signal?.aborted) throw signal.reason ?? new Error('App integrity was cancelled.');
}

function integrityErrorCode(error: unknown): string | null {
  if (!error || typeof error !== 'object' || !('code' in error)) return null;
  return typeof error.code === 'string' ? error.code : null;
}

export function resetAppIntegrityRuntimeForTests(): void {
  playProviderPreparation = null;
}
