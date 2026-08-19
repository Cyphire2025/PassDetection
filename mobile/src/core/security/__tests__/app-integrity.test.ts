import * as AppIntegrity from '@expo/app-integrity';
import * as Crypto from 'expo-crypto';
import { Platform } from 'react-native';

import { ApiError, apiRequest } from '@/core/api/client';
import { env } from '@/core/config/env';
import {
  clearAppAttestKeyRecord,
  getAppAttestKeyRecord,
  getInstallationId,
  setAppAttestKeyRecord,
} from '@/core/storage/secure-store';

import {
  AppIntegrityUnsupportedError,
  createDocumentAuthorizationIntegrityProof,
  resetAppIntegrityRuntimeForTests,
} from '../app-integrity';

jest.mock('@expo/app-integrity', () => ({
  isSupported: true,
  generateKeyAsync: jest.fn(),
  attestKeyAsync: jest.fn(),
  generateAssertionAsync: jest.fn(),
  prepareIntegrityTokenProviderAsync: jest.fn(),
  requestIntegrityCheckAsync: jest.fn(),
}));

jest.mock('expo-crypto', () => ({
  CryptoDigestAlgorithm: { SHA256: 'SHA-256' },
  CryptoEncoding: { BASE64: 'base64' },
  digestStringAsync: jest.fn(async () =>
    'n4vIGWzjVPtLjuR5dzesemNp9He/OVI9KnMEHEsw/34='),
}));

jest.mock('@/core/api/client', () => {
  const actual = jest.requireActual('@/core/api/client');
  return {
    ...actual,
    apiRequest: jest.fn(),
  };
});

jest.mock('@/core/config/env', () => ({
  env: {
    appIntegrityMode: 'enforce',
    playIntegrityCloudProjectNumber: '123456789012',
  },
}));

jest.mock('@/core/storage/secure-store', () => ({
  clearAppAttestKeyRecord: jest.fn(),
  getAppAttestKeyRecord: jest.fn(),
  getInstallationId: jest.fn(),
  setAppAttestKeyRecord: jest.fn(),
}));

const mockedApiRequest = jest.mocked(apiRequest);
const mockedGetInstallationId = jest.mocked(getInstallationId);
const mockedGetAppAttestKeyRecord = jest.mocked(getAppAttestKeyRecord);
const mockedSetAppAttestKeyRecord = jest.mocked(setAppAttestKeyRecord);
const mockedClearAppAttestKeyRecord = jest.mocked(clearAppAttestKeyRecord);
const mutableEnv = env as {
  appIntegrityMode: 'disabled' | 'monitor' | 'enforce';
  playIntegrityCloudProjectNumber?: string;
};

const input = {
  namespace: 'account-namespace',
  tripId: '11111111-1111-4111-8111-111111111111',
  documentId: '22222222-2222-4222-8222-222222222222',
  version: 7,
} as const;
const installationId = 'installation-identifier-0001';
const providerRequestHash = 'P'.repeat(43);

function challenge(
  provider: 'play_integrity' | 'app_attest',
  challengeId = '33333333-3333-4333-8333-333333333333',
) {
  return {
    status: 'issued' as const,
    mode: 'enforce' as const,
    required: true,
    provider,
    challenge_id: challengeId,
    provider_request_hash: providerRequestHash,
    expires_at: '2999-01-01T00:00:00.000Z',
  };
}

function setPlatform(os: 'android' | 'ios' | 'web'): void {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: os });
}

beforeEach(() => {
  jest.clearAllMocks();
  resetAppIntegrityRuntimeForTests();
  mutableEnv.appIntegrityMode = 'enforce';
  mutableEnv.playIntegrityCloudProjectNumber = '123456789012';
  mockedGetInstallationId.mockResolvedValue(installationId);
  mockedGetAppAttestKeyRecord.mockResolvedValue(null);
  mockedSetAppAttestKeyRecord.mockResolvedValue();
  mockedClearAppAttestKeyRecord.mockResolvedValue();
  jest.mocked(AppIntegrity.prepareIntegrityTokenProviderAsync).mockResolvedValue();
  jest.mocked(AppIntegrity.requestIntegrityCheckAsync).mockResolvedValue(
    'opaque-play-integrity-proof',
  );
});

describe('mobile app-integrity proof client', () => {
  it('binds Android proof generation to the canonical resource hash and server challenge', async () => {
    setPlatform('android');
    mockedApiRequest.mockResolvedValueOnce(challenge('play_integrity'));

    await expect(createDocumentAuthorizationIntegrityProof(input)).resolves.toEqual({
      challenge_id: '33333333-3333-4333-8333-333333333333',
      provider: 'play_integrity',
      proof: 'opaque-play-integrity-proof',
      installation_id: installationId,
    });

    const canonical = (
      `gc-mobile-integrity-v1\0document_download_authorize\0${input.tripId}`
      + `\0${input.documentId}\0${input.version}`
    );
    const expectedRequestHash = 'n4vIGWzjVPtLjuR5dzesemNp9He_OVI9KnMEHEsw_34';
    expect(Crypto.digestStringAsync).toHaveBeenCalledWith(
      Crypto.CryptoDigestAlgorithm.SHA256,
      canonical,
      { encoding: Crypto.CryptoEncoding.BASE64 },
    );
    expect(mockedApiRequest).toHaveBeenCalledWith('/mobile/integrity/challenges',
      expect.objectContaining({
        method: 'POST',
        body: {
          provider: 'play_integrity',
          action: 'document_download_authorize',
          request_hash: expectedRequestHash,
          installation_id: installationId,
        },
      }));
    expect(AppIntegrity.prepareIntegrityTokenProviderAsync).toHaveBeenCalledWith(
      '123456789012',
    );
    expect(AppIntegrity.requestIntegrityCheckAsync).toHaveBeenCalledWith(
      providerRequestHash,
    );
  });

  it('re-prepares the standard token provider once when Google invalidates it', async () => {
    setPlatform('android');
    mockedApiRequest.mockResolvedValueOnce(challenge('play_integrity'));
    jest.mocked(AppIntegrity.requestIntegrityCheckAsync)
      .mockRejectedValueOnce({ code: 'ERR_APP_INTEGRITY_PROVIDER_INVALID' })
      .mockResolvedValueOnce('opaque-play-integrity-proof');

    await createDocumentAuthorizationIntegrityProof(input);

    expect(AppIntegrity.prepareIntegrityTokenProviderAsync).toHaveBeenCalledTimes(2);
    expect(AppIntegrity.requestIntegrityCheckAsync).toHaveBeenCalledTimes(2);
  });

  it('registers an iOS Secure Enclave key before generating an assertion', async () => {
    setPlatform('ios');
    Object.defineProperty(AppIntegrity, 'isSupported', {
      configurable: true,
      value: true,
    });
    const keyId = 'K'.repeat(48);
    jest.mocked(AppIntegrity.generateKeyAsync).mockResolvedValue(keyId);
    jest.mocked(AppIntegrity.attestKeyAsync).mockResolvedValue(
      'opaque-app-attest-registration-object',
    );
    jest.mocked(AppIntegrity.generateAssertionAsync).mockResolvedValue(
      'opaque-app-attest-assertion-object',
    );
    mockedApiRequest
      .mockResolvedValueOnce(challenge(
        'app_attest',
        '44444444-4444-4444-8444-444444444444',
      ))
      .mockResolvedValueOnce({ registered: true })
      .mockResolvedValueOnce(challenge('app_attest'));

    await expect(createDocumentAuthorizationIntegrityProof(input)).resolves.toEqual({
      challenge_id: '33333333-3333-4333-8333-333333333333',
      provider: 'app_attest',
      proof: 'opaque-app-attest-assertion-object',
      installation_id: installationId,
      key_id: keyId,
    });

    expect(mockedSetAppAttestKeyRecord).toHaveBeenNthCalledWith(1, input.namespace, {
      formatVersion: 1,
      keyId,
      registered: false,
    });
    expect(AppIntegrity.attestKeyAsync).toHaveBeenCalledWith(
      keyId,
      providerRequestHash,
    );
    expect(mockedApiRequest).toHaveBeenNthCalledWith(2,
      '/mobile/integrity/app-attest/keys/register',
      expect.objectContaining({
        body: {
          challenge_id: '44444444-4444-4444-8444-444444444444',
          installation_id: installationId,
          key_id: keyId,
          attestation_object: 'opaque-app-attest-registration-object',
        },
      }));
    expect(mockedSetAppAttestKeyRecord).toHaveBeenNthCalledWith(2, input.namespace, {
      formatVersion: 1,
      keyId,
      registered: true,
    });
    expect(AppIntegrity.generateAssertionAsync).toHaveBeenCalledWith(
      keyId,
      providerRequestHash,
    );
  });

  it('keeps an unregistered Apple key across a retryable server outage', async () => {
    setPlatform('ios');
    Object.defineProperty(AppIntegrity, 'isSupported', {
      configurable: true,
      value: true,
    });
    jest.mocked(AppIntegrity.generateKeyAsync).mockResolvedValue('K'.repeat(48));
    jest.mocked(AppIntegrity.attestKeyAsync).mockResolvedValue(
      'opaque-app-attest-registration-object',
    );
    mockedApiRequest
      .mockResolvedValueOnce(challenge('app_attest'))
      .mockRejectedValueOnce(new ApiError('outage', 503, 'HTTP_503', 30));

    await expect(createDocumentAuthorizationIntegrityProof(input)).rejects.toBeInstanceOf(
      ApiError,
    );
    expect(mockedClearAppAttestKeyRecord).not.toHaveBeenCalled();
  });

  it('degrades unsupported platforms only in monitor mode', async () => {
    setPlatform('web');
    mutableEnv.appIntegrityMode = 'monitor';

    await expect(createDocumentAuthorizationIntegrityProof(input)).resolves.toBeUndefined();

    mutableEnv.appIntegrityMode = 'enforce';
    await expect(createDocumentAuthorizationIntegrityProof(input)).rejects.toBeInstanceOf(
      AppIntegrityUnsupportedError,
    );
  });

  it('never turns caller cancellation into monitor-mode success', async () => {
    setPlatform('android');
    mutableEnv.appIntegrityMode = 'monitor';
    const controller = new AbortController();
    const reason = new Error('caller cancelled');
    controller.abort(reason);

    await expect(
      createDocumentAuthorizationIntegrityProof(input, controller.signal),
    ).rejects.toBe(reason);
    expect(mockedApiRequest).not.toHaveBeenCalled();
  });

  it('does no platform, installation, or network work while disabled', async () => {
    mutableEnv.appIntegrityMode = 'disabled';

    await expect(createDocumentAuthorizationIntegrityProof(input)).resolves.toBeUndefined();

    expect(mockedGetInstallationId).not.toHaveBeenCalled();
    expect(mockedApiRequest).not.toHaveBeenCalled();
    expect(AppIntegrity.requestIntegrityCheckAsync).not.toHaveBeenCalled();
  });
});
