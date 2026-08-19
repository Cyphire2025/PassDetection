import { ed25519 } from '@noble/curves/ed25519.js';
import { base64urlnopad } from '@scure/base';

import {
  acceptOnlineOfflineAuthorizationLease,
  authorizeStoredOfflineLease,
  OfflineAuthorizationError,
  parseOfflineAuthorizationVerificationConfiguration,
  resetOfflineAuthorizationRuntimeForTests,
  verifyOfflineAuthorizationLease,
  type OfflineAuthorizationExpectedIdentity,
  type OfflineAuthorizationVerificationConfiguration,
} from '../offline-authorization';

const ISSUED_AT_SECONDS = 1_900_000_000;
const PRIVATE_KEY = Uint8Array.from({ length: 32 }, (_, index) => index + 1);
const PUBLIC_KEY = ed25519.getPublicKey(PRIVATE_KEY);
const SECOND_PRIVATE_KEY = Uint8Array.from({ length: 32 }, (_, index) => 32 - index);
const SECOND_PUBLIC_KEY = ed25519.getPublicKey(SECOND_PRIVATE_KEY);

const expected: OfflineAuthorizationExpectedIdentity = {
  installationId: '8fbcbd0e-72d3-49bc-a092-5f1974949b1d',
  sessionId: '5f1df101-41e8-4bbc-9abc-3c34fae88ddf',
  principalId: '9a3dfcd7-5488-49c8-a2d4-4d1d361ebda7',
  accountId: 'ee9cff07-f510-456a-bf83-75d363e5555e',
  agencyId: '6391dafc-096d-4a54-8908-f2c1cf3e524c',
  principalType: 'passenger',
  passengerId: '0d710858-cb4f-452e-bcf4-c06897238666',
};

const configuration: OfflineAuthorizationVerificationConfiguration =
  parseOfflineAuthorizationVerificationConfiguration({
    issuer: 'passdetection-mobile-offline',
    audience: 'gc-mobile-offline',
    publicKeysJson: `{"current":"${base64urlnopad.encode(PUBLIC_KEY)}"}`,
  });

function asciiBytes(value: string): Uint8Array {
  return Uint8Array.from(value, (character) => character.charCodeAt(0));
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === 'string' || typeof value === 'boolean' || typeof value === 'number') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
    .join(',')}}`;
}

function baseClaims(): Record<string, unknown> {
  return {
    access_generation: 7,
    account_id: expected.accountId,
    agency_id: expected.agencyId,
    aud: 'gc-mobile-offline',
    exp: ISSUED_AT_SECONDS + 43_200,
    format_version: 1,
    iat: ISSUED_AT_SECONDS,
    installation_id: expected.installationId,
    iss: 'passdetection-mobile-offline',
    jti: 'cc2e08e0-ad17-48af-8ccb-cee5f41e825d',
    nbf: ISSUED_AT_SECONDS,
    passenger_id: expected.passengerId,
    principal_generation: 4,
    principal_type: expected.principalType,
    server_time: ISSUED_AT_SECONDS,
    session_generation: 3,
    session_id: expected.sessionId,
    sub: expected.principalId,
  };
}

function createLease(options: Readonly<{
  claims?: Record<string, unknown>;
  header?: Record<string, unknown>;
  privateKey?: Uint8Array;
  rawClaimsJson?: string;
}> = {}): string {
  const header = options.header ?? {
    alg: 'EdDSA',
    kid: 'current',
    typ: 'GC-OFFLINE-AUTH',
    v: 1,
  };
  const encodedHeader = base64urlnopad.encode(asciiBytes(canonicalJson(header)));
  const claimsJson = options.rawClaimsJson ?? canonicalJson(options.claims ?? baseClaims());
  const encodedClaims = base64urlnopad.encode(asciiBytes(claimsJson));
  const signingInput = asciiBytes(`${encodedHeader}.${encodedClaims}`);
  const signature = ed25519.sign(signingInput, options.privateKey ?? PRIVATE_KEY);
  return `${encodedHeader}.${encodedClaims}.${base64urlnopad.encode(signature)}`;
}

function expectCode(operation: () => unknown, code: OfflineAuthorizationError['code']): void {
  try {
    operation();
  } catch (error) {
    expect(error).toBeInstanceOf(OfflineAuthorizationError);
    expect((error as OfflineAuthorizationError).code).toBe(code);
    return;
  }
  throw new Error(`Expected offline authorization rejection (${code}).`);
}

describe('offline authorization lease verification', () => {
  beforeEach(() => resetOfflineAuthorizationRuntimeForTests());

  it('accepts the canonical strict Ed25519 profile and exact bound identity', () => {
    const claims = verifyOfflineAuthorizationLease(createLease(), expected, configuration);

    expect(claims).toMatchObject({
      sub: expected.principalId,
      account_id: expected.accountId,
      agency_id: expected.agencyId,
      session_id: expected.sessionId,
      installation_id: expected.installationId,
      session_generation: 3,
      principal_generation: 4,
      access_generation: 7,
    });
    expect(claims).not.toHaveProperty('display_name');
    expect(claims).not.toHaveProperty('email');
    expect(claims).not.toHaveProperty('phone_number');
    expect(claims).not.toHaveProperty('access_token');
    expect(claims).not.toHaveProperty('refresh_token');
  });

  it('rejects tampering, algorithm substitution, extra claims, and non-canonical JSON', () => {
    const lease = createLease();
    const [header, payload, signature] = lease.split('.');
    expectCode(
      () => verifyOfflineAuthorizationLease(
        `${header}.${payload}.${signature?.startsWith('A') ? 'B' : 'A'}${signature?.slice(1)}`,
        expected,
        configuration,
      ),
      'signature',
    );
    expectCode(
      () => verifyOfflineAuthorizationLease(
        createLease({ header: { alg: 'HS256', kid: 'current', typ: 'GC-OFFLINE-AUTH', v: 1 } }),
        expected,
        configuration,
      ),
      'malformed',
    );
    expectCode(
      () => verifyOfflineAuthorizationLease(
        createLease({ claims: { ...baseClaims(), display_name: 'Must not be signed' } }),
        expected,
        configuration,
      ),
      'malformed',
    );
    const claims = canonicalJson(baseClaims());
    expectCode(
      () => verifyOfflineAuthorizationLease(
        createLease({ rawClaimsJson: `{ "access_generation":7,${claims.slice(1)}` }),
        expected,
        configuration,
      ),
      'malformed',
    );
  });

  it.each([
    ['installation_id', '00000000-0000-4000-8000-000000000001'],
    ['session_id', '00000000-0000-4000-8000-000000000002'],
    ['sub', '00000000-0000-4000-8000-000000000003'],
    ['account_id', '00000000-0000-4000-8000-000000000004'],
    ['agency_id', '00000000-0000-4000-8000-000000000005'],
    ['passenger_id', '00000000-0000-4000-8000-000000000006'],
    ['principal_type', 'coordinator'],
  ] as const)('rejects a signed lease with swapped %s', (field, value) => {
    expectCode(
      () => verifyOfflineAuthorizationLease(
        createLease({ claims: { ...baseClaims(), [field]: value } }),
        expected,
        configuration,
      ),
      'identity',
    );
  });

  it('supports a bounded rotation set and rejects an unknown key id', () => {
    const rotatingConfiguration = parseOfflineAuthorizationVerificationConfiguration({
      issuer: 'passdetection-mobile-offline',
      audience: 'gc-mobile-offline',
      publicKeysJson: canonicalJson({
        current: base64urlnopad.encode(PUBLIC_KEY),
        next: base64urlnopad.encode(SECOND_PUBLIC_KEY),
      }),
    });
    expect(() => verifyOfflineAuthorizationLease(
      createLease({
        header: { alg: 'EdDSA', kid: 'next', typ: 'GC-OFFLINE-AUTH', v: 1 },
        privateKey: SECOND_PRIVATE_KEY,
      }),
      expected,
      rotatingConfiguration,
    )).not.toThrow();
    expectCode(
      () => verifyOfflineAuthorizationLease(
        createLease({
          header: { alg: 'EdDSA', kid: 'retired', typ: 'GC-OFFLINE-AUTH', v: 1 },
        }),
        expected,
        configuration,
      ),
      'unknown_key',
    );
  });

  it('rejects malformed, non-canonical, and oversized public key sets', () => {
    expectCode(
      () => parseOfflineAuthorizationVerificationConfiguration({
        issuer: 'passdetection-mobile-offline',
        audience: 'gc-mobile-offline',
        publicKeysJson: `{ "current": "${base64urlnopad.encode(PUBLIC_KEY)}" }`,
      }),
      'configuration',
    );
    expectCode(
      () => parseOfflineAuthorizationVerificationConfiguration({
        issuer: 'passdetection-mobile-offline',
        audience: 'gc-mobile-offline',
        publicKeysJson: canonicalJson(Object.fromEntries(
          Array.from({ length: 6 }, (_, index) => [`key-${index}`, base64urlnopad.encode(PUBLIC_KEY)]),
        )),
      }),
      'configuration',
    );
    expectCode(
      () => parseOfflineAuthorizationVerificationConfiguration({
        issuer: 'passdetection-mobile-offline',
        audience: 'gc-mobile-offline',
        publicKeysJson: canonicalJson({ current: base64urlnopad.encode(new Uint8Array(32).fill(0xff)) }),
      }),
      'configuration',
    );
  });

  it('advances trusted time monotonically within a boot and across a restart anchor', () => {
    const lease = createLease();
    const accepted = acceptOnlineOfflineAuthorizationLease(
      lease,
      expected,
      configuration,
      { wallTimeMs: 10_000, monotonicTimeMs: 100 },
    );
    const sameBoot = authorizeStoredOfflineLease(
      accepted.record,
      expected,
      configuration,
      { wallTimeMs: 10_250, monotonicTimeMs: 350 },
    );
    expect(sameBoot.trustedServerTimeMs).toBe((ISSUED_AT_SECONDS * 1_000) + 250);

    resetOfflineAuthorizationRuntimeForTests();
    const afterRestart = authorizeStoredOfflineLease(
      sameBoot.record,
      expected,
      configuration,
      { wallTimeMs: 70_250, monotonicTimeMs: 5 },
    );
    expect(afterRestart.trustedServerTimeMs).toBe((ISSUED_AT_SECONDS * 1_000) + 60_250);
  });

  it('rejects wall and monotonic rollback, future records, and expiry', () => {
    const accepted = acceptOnlineOfflineAuthorizationLease(
      createLease(),
      expected,
      configuration,
      { wallTimeMs: 100_000, monotonicTimeMs: 1_000 },
    );
    expectCode(
      () => authorizeStoredOfflineLease(
        accepted.record,
        expected,
        configuration,
        { wallTimeMs: 99_999, monotonicTimeMs: 1_001 },
      ),
      'clock_rollback',
    );
    expectCode(
      () => authorizeStoredOfflineLease(
        accepted.record,
        expected,
        configuration,
        { wallTimeMs: 100_001, monotonicTimeMs: 999 },
      ),
      'clock_rollback',
    );
    expectCode(
      () => authorizeStoredOfflineLease(
        { ...accepted.record, highWaterServerTimeMs: accepted.record.highWaterServerTimeMs - 1 },
        expected,
        configuration,
        { wallTimeMs: 100_001, monotonicTimeMs: 1_001 },
      ),
      'future',
    );

    resetOfflineAuthorizationRuntimeForTests();
    expectCode(
      () => authorizeStoredOfflineLease(
        accepted.record,
        expected,
        configuration,
        { wallTimeMs: 100_000 + 43_200_000, monotonicTimeMs: 1 },
      ),
      'expired',
    );
  });
});
