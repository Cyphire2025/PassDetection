import { ed25519 } from '@noble/curves/ed25519.js';
import { base64urlnopad } from '@scure/base';

import {
  DEFAULT_OFFLINE_AUTHORIZATION_AUDIENCE,
  DEFAULT_OFFLINE_AUTHORIZATION_ISSUER,
  DEFAULT_OFFLINE_AUTHORIZATION_PUBLIC_KEYS_JSON,
} from '../config/offline-authorization-public';
import { z } from 'zod';

import type { OfflineAuthorizationRecord } from '@/core/storage/secure-store';

const COMPACT_LEASE_PATTERN = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;
const KEY_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const LEASE_IDENTITY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:/-]{2,119}$/;
const INSTALLATION_ID_PATTERN = /^[A-Za-z0-9._:-]{16,128}$/;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const MAX_COMPACT_LEASE_LENGTH = 4_096;
const MAX_HEADER_BYTES = 512;
const MAX_PAYLOAD_BYTES = 3_072;
const MAX_VERIFICATION_KEYS = 5;
const MIN_LEASE_LIFETIME_SECONDS = 5 * 60;
const MAX_LEASE_LIFETIME_SECONDS = 24 * 60 * 60;

const SafeTimestamp = z.number().int().min(1).max(Number.MAX_SAFE_INTEGER);
const Generation = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
const Uuid = z.string().regex(UUID_PATTERN);

const HeaderSchema = z.object({
  alg: z.literal('EdDSA'),
  kid: z.string().regex(KEY_ID_PATTERN),
  typ: z.literal('GC-OFFLINE-AUTH'),
  v: z.literal(1),
}).strict();

const ClaimsSchema = z.object({
  access_generation: Generation.nullable(),
  account_id: Uuid,
  agency_id: Uuid,
  aud: z.string().regex(LEASE_IDENTITY_PATTERN),
  exp: SafeTimestamp,
  format_version: z.literal(1),
  iat: SafeTimestamp,
  installation_id: z.string().regex(INSTALLATION_ID_PATTERN),
  iss: z.string().regex(LEASE_IDENTITY_PATTERN),
  jti: Uuid,
  nbf: SafeTimestamp,
  passenger_id: Uuid.nullable(),
  principal_generation: Generation.nullable(),
  principal_type: z.enum(['passenger', 'client_manager', 'coordinator']),
  server_time: SafeTimestamp,
  session_generation: z.number().int().min(1).max(Number.MAX_SAFE_INTEGER),
  session_id: Uuid,
  sub: Uuid,
}).strict();

export type OfflineAuthorizationClaims = Readonly<z.infer<typeof ClaimsSchema>>;

export type OfflineAuthorizationExpectedIdentity = Readonly<{
  installationId: string;
  sessionId: string;
  principalId: string;
  accountId: string;
  agencyId: string;
  principalType: 'passenger' | 'client_manager' | 'coordinator';
  passengerId: string | null;
}>;

export type OfflineAuthorizationVerificationConfiguration = Readonly<{
  issuer: string;
  audience: string;
  /** Canonical, unpadded base64url-encoded raw Ed25519 public keys by kid. */
  verificationKeys: Readonly<Record<string, string>>;
}>;

export type OfflineAuthorizationClock = Readonly<{
  wallTimeMs: number;
  monotonicTimeMs: number;
}>;

export type AuthorizedOfflineLease = Readonly<{
  claims: OfflineAuthorizationClaims;
  record: OfflineAuthorizationRecord;
  trustedServerTimeMs: number;
  remainingMs: number;
}>;

export type OfflineAuthorizationErrorCode =
  | 'configuration'
  | 'malformed'
  | 'unknown_key'
  | 'signature'
  | 'identity'
  | 'future'
  | 'expired'
  | 'clock_rollback'
  | 'clock_unavailable';

export class OfflineAuthorizationError extends Error {
  readonly code: OfflineAuthorizationErrorCode;

  constructor(code: OfflineAuthorizationErrorCode) {
    super(`Offline authorization rejected (${code}).`);
    this.name = 'OfflineAuthorizationError';
    this.code = code;
  }
}

type BootTimeAnchor = Readonly<{
  compactLease: string;
  monotonicAtStartMs: number;
  trustedAtStartMs: number;
}>;

const bootTimeAnchors = new Map<string, BootTimeAnchor>();
let runtimeConfiguration: OfflineAuthorizationVerificationConfiguration | null = null;

function reject(code: OfflineAuthorizationErrorCode): never {
  throw new OfflineAuthorizationError(code);
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') {
    return JSON.stringify(value);
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) reject('malformed');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(',')}]`;
  }
  if (typeof value !== 'object') reject('malformed');
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
    .join(',')}}`;
}

function asciiBytes(value: string): Uint8Array {
  const result = new Uint8Array(value.length);
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code > 0x7f) reject('malformed');
    result[index] = code;
  }
  return result;
}

function asciiString(value: Uint8Array, maximumLength: number): string {
  if (value.length === 0 || value.length > maximumLength) reject('malformed');
  let result = '';
  for (const byte of value) {
    if (byte > 0x7f) reject('malformed');
    result += String.fromCharCode(byte);
  }
  return result;
}

function decodeCanonicalBase64url(value: string, maximumBytes: number): Uint8Array {
  if (!value || !/^[A-Za-z0-9_-]+$/.test(value)) reject('malformed');
  try {
    const decoded = base64urlnopad.decode(value);
    if (decoded.length === 0 || decoded.length > maximumBytes) reject('malformed');
    if (base64urlnopad.encode(decoded) !== value) reject('malformed');
    return decoded;
  } catch (error) {
    if (error instanceof OfflineAuthorizationError) throw error;
    reject('malformed');
  }
}

function parseCanonicalJsonSegment(
  segment: string,
  maximumBytes: number,
): unknown {
  const decodedJson = asciiString(
    decodeCanonicalBase64url(segment, maximumBytes),
    maximumBytes,
  );
  let parsed: unknown;
  try {
    parsed = JSON.parse(decodedJson) as unknown;
  } catch {
    reject('malformed');
  }
  if (canonicalJson(parsed) !== decodedJson) reject('malformed');
  return parsed;
}

function safeClock(clock?: OfflineAuthorizationClock): OfflineAuthorizationClock {
  const resolved = clock ?? {
    wallTimeMs: Date.now(),
    monotonicTimeMs: globalThis.performance?.now(),
  };
  if (
    !Number.isSafeInteger(resolved.wallTimeMs)
    || resolved.wallTimeMs < 0
    || !Number.isFinite(resolved.monotonicTimeMs)
    || resolved.monotonicTimeMs < 0
  ) {
    reject('clock_unavailable');
  }
  return resolved;
}

function anchorKey(expected: OfflineAuthorizationExpectedIdentity): string {
  return `${expected.installationId}:${expected.sessionId}`;
}

function setBootAnchor(
  expected: OfflineAuthorizationExpectedIdentity,
  anchor: BootTimeAnchor,
): void {
  const key = anchorKey(expected);
  bootTimeAnchors.delete(key);
  bootTimeAnchors.set(key, anchor);
  while (bootTimeAnchors.size > 8) {
    const oldestKey = bootTimeAnchors.keys().next().value as string | undefined;
    if (oldestKey === undefined) break;
    bootTimeAnchors.delete(oldestKey);
  }
}

function assertExactIdentity(
  claims: OfflineAuthorizationClaims,
  expected: OfflineAuthorizationExpectedIdentity,
): void {
  if (
    claims.installation_id !== expected.installationId
    || claims.session_id !== expected.sessionId
    || claims.sub !== expected.principalId
    || claims.account_id !== expected.accountId
    || claims.agency_id !== expected.agencyId
    || claims.principal_type !== expected.principalType
    || claims.passenger_id !== expected.passengerId
    || (claims.principal_type === 'passenger' && claims.passenger_id === null)
    || (claims.principal_type !== 'passenger' && claims.passenger_id !== null)
  ) {
    reject('identity');
  }
}

function parseVerificationKey(encodedKey: string): Uint8Array {
  const key = decodeCanonicalBase64url(encodedKey, 32);
  if (key.length !== 32) reject('configuration');
  try {
    if (!ed25519.utils.isValidPublicKey(key, false)) reject('configuration');
  } catch (error) {
    if (error instanceof OfflineAuthorizationError) throw error;
    reject('configuration');
  }
  return key;
}

export function parseOfflineAuthorizationVerificationConfiguration(input: Readonly<{
  issuer: string | undefined;
  audience: string | undefined;
  publicKeysJson: string | undefined;
}>): OfflineAuthorizationVerificationConfiguration {
  if (
    !input.issuer
    || !LEASE_IDENTITY_PATTERN.test(input.issuer)
    || !input.audience
    || !LEASE_IDENTITY_PATTERN.test(input.audience)
    || !input.publicKeysJson
    || input.publicKeysJson.length > 8_192
  ) {
    reject('configuration');
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(input.publicKeysJson) as unknown;
  } catch {
    reject('configuration');
  }
  if (
    !parsed
    || typeof parsed !== 'object'
    || Array.isArray(parsed)
    || canonicalJson(parsed) !== input.publicKeysJson
  ) {
    reject('configuration');
  }

  const entries = Object.entries(parsed as Record<string, unknown>);
  if (entries.length < 1 || entries.length > MAX_VERIFICATION_KEYS) {
    reject('configuration');
  }
  const verificationKeys: Record<string, string> = Object.create(null) as Record<string, string>;
  for (const [kid, encodedKey] of entries) {
    if (!KEY_ID_PATTERN.test(kid) || typeof encodedKey !== 'string') {
      reject('configuration');
    }
    try {
      parseVerificationKey(encodedKey);
    } catch {
      reject('configuration');
    }
    verificationKeys[kid] = encodedKey;
  }
  return Object.freeze({
    issuer: input.issuer,
    audience: input.audience,
    verificationKeys: Object.freeze(verificationKeys),
  });
}

export function getOfflineAuthorizationVerificationConfiguration(): OfflineAuthorizationVerificationConfiguration {
  runtimeConfiguration ??= parseOfflineAuthorizationVerificationConfiguration({
    issuer:
      process.env.EXPO_PUBLIC_OFFLINE_LEASE_ISSUER
      ?? DEFAULT_OFFLINE_AUTHORIZATION_ISSUER,
    audience:
      process.env.EXPO_PUBLIC_OFFLINE_LEASE_AUDIENCE
      ?? DEFAULT_OFFLINE_AUTHORIZATION_AUDIENCE,
    publicKeysJson:
      process.env.EXPO_PUBLIC_OFFLINE_LEASE_PUBLIC_KEYS_JSON
      ?? DEFAULT_OFFLINE_AUTHORIZATION_PUBLIC_KEYS_JSON,
  });
  return runtimeConfiguration;
}

export function verifyOfflineAuthorizationLease(
  compactLease: string,
  expected: OfflineAuthorizationExpectedIdentity,
  configuration = getOfflineAuthorizationVerificationConfiguration(),
): OfflineAuthorizationClaims {
  if (
    compactLease.length < 256
    || compactLease.length > MAX_COMPACT_LEASE_LENGTH
    || !COMPACT_LEASE_PATTERN.test(compactLease)
  ) {
    reject('malformed');
  }
  const segments = compactLease.split('.');
  if (segments.length !== 3) reject('malformed');
  const [encodedHeader, encodedClaims, encodedSignature] = segments;
  if (!encodedHeader || !encodedClaims || !encodedSignature) reject('malformed');

  const headerResult = HeaderSchema.safeParse(
    parseCanonicalJsonSegment(encodedHeader, MAX_HEADER_BYTES),
  );
  if (!headerResult.success) reject('malformed');
  const encodedKey = Object.prototype.hasOwnProperty.call(
    configuration.verificationKeys,
    headerResult.data.kid,
  )
    ? configuration.verificationKeys[headerResult.data.kid]
    : undefined;
  if (typeof encodedKey !== 'string') reject('unknown_key');
  let verificationKey: Uint8Array;
  try {
    verificationKey = parseVerificationKey(encodedKey);
  } catch {
    reject('configuration');
  }
  const signature = decodeCanonicalBase64url(encodedSignature, 64);
  if (signature.length !== 64) reject('malformed');
  const signingInput = asciiBytes(`${encodedHeader}.${encodedClaims}`);
  let valid = false;
  try {
    // Disable ZIP-215's more permissive point-decoding rules. This profile uses
    // strict RFC 8032 verification for one canonical signature representation.
    valid = ed25519.verify(signature, signingInput, verificationKey, { zip215: false });
  } catch {
    valid = false;
  }
  if (!valid) reject('signature');

  // Claims influence authorization only after the signature over their exact
  // encoded bytes has been accepted.
  const claimsResult = ClaimsSchema.safeParse(
    parseCanonicalJsonSegment(encodedClaims, MAX_PAYLOAD_BYTES),
  );
  if (!claimsResult.success) reject('malformed');
  const claims = claimsResult.data;
  if (
    claims.iss !== configuration.issuer
    || claims.aud !== configuration.audience
  ) {
    reject('identity');
  }
  if (
    claims.iat !== claims.nbf
    || claims.iat !== claims.server_time
    || claims.exp - claims.iat < MIN_LEASE_LIFETIME_SECONDS
    || claims.exp - claims.iat > MAX_LEASE_LIFETIME_SECONDS
  ) {
    reject('malformed');
  }
  assertExactIdentity(claims, expected);
  return claims;
}

export function acceptOnlineOfflineAuthorizationLease(
  compactLease: string,
  expected: OfflineAuthorizationExpectedIdentity,
  configuration = getOfflineAuthorizationVerificationConfiguration(),
  clock?: OfflineAuthorizationClock,
): AuthorizedOfflineLease {
  const claims = verifyOfflineAuthorizationLease(compactLease, expected, configuration);
  const resolvedClock = safeClock(clock);
  const trustedServerTimeMs = claims.server_time * 1_000;
  const expiresAtMs = claims.exp * 1_000;
  if (trustedServerTimeMs < claims.nbf * 1_000) reject('future');
  if (trustedServerTimeMs >= expiresAtMs) reject('expired');

  const record: OfflineAuthorizationRecord = {
    formatVersion: 1,
    compactLease,
    highWaterServerTimeMs: trustedServerTimeMs,
    anchoredWallClockMs: resolvedClock.wallTimeMs,
  };
  setBootAnchor(expected, {
    compactLease,
    monotonicAtStartMs: resolvedClock.monotonicTimeMs,
    trustedAtStartMs: trustedServerTimeMs,
  });
  return {
    claims,
    record,
    trustedServerTimeMs,
    remainingMs: expiresAtMs - trustedServerTimeMs,
  };
}

export function authorizeStoredOfflineLease(
  record: OfflineAuthorizationRecord,
  expected: OfflineAuthorizationExpectedIdentity,
  configuration = getOfflineAuthorizationVerificationConfiguration(),
  clock?: OfflineAuthorizationClock,
): AuthorizedOfflineLease {
  const claims = verifyOfflineAuthorizationLease(record.compactLease, expected, configuration);
  const resolvedClock = safeClock(clock);
  const signedServerTimeMs = claims.server_time * 1_000;
  const notBeforeMs = claims.nbf * 1_000;
  const expiresAtMs = claims.exp * 1_000;

  if (
    record.formatVersion !== 1
    || !Number.isSafeInteger(record.highWaterServerTimeMs)
    || !Number.isSafeInteger(record.anchoredWallClockMs)
    || resolvedClock.wallTimeMs < record.anchoredWallClockMs
  ) {
    reject('clock_rollback');
  }
  if (record.highWaterServerTimeMs < signedServerTimeMs) reject('future');

  const existingAnchor = bootTimeAnchors.get(anchorKey(expected));
  let trustedServerTimeMs: number;
  if (existingAnchor?.compactLease === record.compactLease) {
    if (resolvedClock.monotonicTimeMs < existingAnchor.monotonicAtStartMs) {
      reject('clock_rollback');
    }
    trustedServerTimeMs = Math.max(
      record.highWaterServerTimeMs,
      existingAnchor.trustedAtStartMs
        + (resolvedClock.monotonicTimeMs - existingAnchor.monotonicAtStartMs),
    );
  } else {
    trustedServerTimeMs = record.highWaterServerTimeMs
      + (resolvedClock.wallTimeMs - record.anchoredWallClockMs);
    setBootAnchor(expected, {
      compactLease: record.compactLease,
      monotonicAtStartMs: resolvedClock.monotonicTimeMs,
      trustedAtStartMs: trustedServerTimeMs,
    });
  }

  if (!Number.isFinite(trustedServerTimeMs) || trustedServerTimeMs < notBeforeMs) {
    reject('future');
  }
  if (trustedServerTimeMs >= expiresAtMs) reject('expired');

  const persistedHighWaterMs = Math.floor(trustedServerTimeMs);
  return {
    claims,
    record: {
      formatVersion: 1,
      compactLease: record.compactLease,
      highWaterServerTimeMs: persistedHighWaterMs,
      anchoredWallClockMs: resolvedClock.wallTimeMs,
    },
    trustedServerTimeMs,
    remainingMs: expiresAtMs - trustedServerTimeMs,
  };
}

export function clearOfflineAuthorizationBootAnchor(expected?: OfflineAuthorizationExpectedIdentity): void {
  if (expected) {
    bootTimeAnchors.delete(anchorKey(expected));
  } else {
    bootTimeAnchors.clear();
  }
}

export function resetOfflineAuthorizationRuntimeForTests(): void {
  runtimeConfiguration = null;
  bootTimeAnchors.clear();
}
