
import { z } from "zod";

import { useAuthStore } from "@/stores/auth.store";
import apiClient from "@/lib/api/client";

import { protectBrowserJson, unprotectBrowserJson, type ProtectedBrowserValue } from "./browser-offline-crypto";
import {
  OFFLINE_AUTHORIZATION_STORE,
  OFFLINE_CRYPTO_KEY_STORE,
  idbRequest,
  idbTransaction,
  openBrowserOfflineDatabase,
} from "./browser-offline-database";

const UUID = z.string().uuid();
const ISO_INSTANT = z.string().datetime({ offset: true });
const BASE64URL = z.string().regex(/^[A-Za-z0-9_-]+$/);
const SHA256_HEX = z.string().regex(/^[0-9a-f]{64}$/);
const MAX_AUTHORIZATION_BYTES = 2 * 1024 * 1024;
const MAX_CLOCK_ROLLBACK_MS = 2 * 60_000;
const MAX_RUNTIME_WALL_DRIFT_MS = 5 * 60_000;
const ACTIVITY_EARLY_SKEW_MS = 5 * 60_000;

const AuthorizedSessionSchema = z.object({
  id: UUID,
  label: z.string().min(1).max(160),
  scheduled_ends_at: ISO_INSTANT,
  scheduled_starts_at: ISO_INSTANT,
  status: z.literal("active"),
}).strict();

const AuthorizedPassengerSchema = z.object({
  id: UUID,
  label: z.string().min(1).max(255),
  token_hash: SHA256_HEX,
  token_valid_until: ISO_INSTANT,
  token_version: z.number().int().positive(),
}).strict();

const AuthorizationPayloadSchema = z.object({
  coordinator_user_id: UUID,
  expires_at: ISO_INSTANT,
  group_id: UUID,
  group_label: z.string().min(1).max(160),
  issued_at: ISO_INSTANT,
  key_id: z.string().min(1).max(80).regex(/^[A-Za-z0-9._-]+$/),
  max_suspension_seconds: z.number().int().min(60).max(7 * 24 * 60 * 60),
  not_before: ISO_INSTANT,
  passengers: z.array(AuthorizedPassengerSchema).max(2_000),
  roster_revision: z.number().int().nonnegative(),
  schema_version: z.literal(1),
  server_time: ISO_INSTANT,
  sessions: z.array(AuthorizedSessionSchema).min(1).max(200),
  tenant_id: UUID,
}).strict();

const AuthorizationBundleSchema = z.object({
  key_id: z.string().min(1).max(80).regex(/^[A-Za-z0-9._-]+$/),
  payload: BASE64URL.max(Math.ceil(MAX_AUTHORIZATION_BYTES * 4 / 3) + 16),
  public_key: BASE64URL.max(64),
  signature: BASE64URL.max(128),
  version: z.literal("pwa-offline-authorization-v1"),
}).strict();

const RuntimeRegistrationSchema = z.object({
  runtime_id: UUID,
  runtime_kind: z.enum(["pwa", "webview"]),
  expires_at: ISO_INSTANT,
}).strict();

export type BrowserOfflineAuthorizationPayload = z.infer<typeof AuthorizationPayloadSchema>;
export type BrowserOfflineAuthorizationBundle = z.infer<typeof AuthorizationBundleSchema>;

type StoredAuthorization = Readonly<{
  agencyId: string;
  expiresAt: string;
  groupId: string;
  id: string;
  keyId: string;
  observedMonotonicMs: number;
  observedWallClockMs: number;
  ownerUserId: string;
  protectedValue: ProtectedBrowserValue;
  trustedHighWaterMs: number;
  runtimeId: string;
  runtimeKind: "pwa" | "webview";
  runtimeExpiresAt: string;
}>;

type StoredAuthorizationValue = Readonly<{
  bundle: BrowserOfflineAuthorizationBundle;
  payload: BrowserOfflineAuthorizationPayload;
}>;

type StoredVerificationKey = Readonly<{
  digest: string;
  id: string;
  key: CryptoKey;
  keyId: string;
}>;

type RuntimeClockAnchor = Readonly<{
  monotonicMs: number;
  trustedServerTimeMs: number;
  wallClockMs: number;
}>;

const runtimeClockAnchors = new Map<string, RuntimeClockAnchor>();

export class BrowserOfflineAuthorizationError extends Error {
  constructor(public readonly code:
    | "ACTIVITY_NOT_AUTHORIZED"
    | "ACTIVITY_OUTSIDE_WINDOW"
    | "AUTHORIZATION_EXPIRED"
    | "AUTHORIZATION_INVALID"
    | "AUTHORIZATION_NOT_AVAILABLE"
    | "CLOCK_ROLLBACK"
    | "CLOCK_SKEW"
    | "QR_NOT_IN_ACTIVE_ROSTER"
    | "TOKEN_EVIDENCE_EXPIRED"
  ) {
    super(code);
    this.name = "BrowserOfflineAuthorizationError";
  }
}

export type AuthorizedBrowserOfflineScan = Readonly<{
  passengerId: string;
  passengerLabel: string;
  scannedAt: string;
  sessionLabel: string;
  trustedServerTimeMs: number;
  runtimeId: string;
}>;

export type BrowserOfflineReadinessEvidence = Readonly<{
  checkedAt: string;
  groupId: string;
  sessionId: string | null;
  validUntil: string;
}>;

/**
 * Provisions a signed manifest over an authenticated HTTPS session. The raw
 * verification key is imported as non-exportable and pinned by key-id/digest;
 * a later response cannot silently replace the same key id.
 */
export async function refreshBrowserOfflineAuthorization(
  groupId: string,
  signal?: AbortSignal,
): Promise<BrowserOfflineAuthorizationPayload> {
  const identity = requireCoordinatorIdentity();
  const controller = signal ? null : new AbortController();
  const timeout = controller ? window.setTimeout(() => controller.abort(), 10_000) : null;
  try {
    // This same-origin mutation passes through the normal cookie/CSRF API
    // boundary. The HttpOnly cookie set by the server is authoritative; the
    // returned UUID is persisted only as a diagnostic/closeout continuity hint.
    const registration = RuntimeRegistrationSchema.parse((await apiClient.post(
      "/api/v1/tour-operations/coordinator/attendance/runtime",
      { runtime_kind: browserRuntimeKind() },
      { signal: signal ?? controller?.signal },
    )).data);
    const response = await window.fetch(
      `/api/v1/tour-operations/coordinator/groups/${encodeURIComponent(groupId)}/offline-authorization`,
      {
        cache: "no-store",
        credentials: "include",
        headers: { Accept: "application/json" },
        signal: signal ?? controller?.signal,
      },
    );
    if (!response.ok) throw new BrowserOfflineAuthorizationError("AUTHORIZATION_NOT_AVAILABLE");
    const bundle = AuthorizationBundleSchema.parse(await response.json());
    const payload = await validateAuthorizationBundle(bundle, identity, groupId, true);
    const now = Date.now();
    const trustedServerTimeMs = requiredInstant(payload.server_time);
    const id = authorizationId(identity, groupId);
    const storedValue: StoredAuthorizationValue = { bundle, payload };
    const protectedValue = await protectBrowserJson(
      storedValue,
      authorizationAssociatedData(id),
    );
    assertCoordinatorIdentityIsCurrent(identity);
    const record: StoredAuthorization = {
      agencyId: identity.agencyId,
      expiresAt: payload.expires_at,
      groupId,
      id,
      keyId: bundle.key_id,
      observedMonotonicMs: performance.now(),
      observedWallClockMs: now,
      ownerUserId: identity.ownerUserId,
      protectedValue,
      trustedHighWaterMs: trustedServerTimeMs,
      runtimeId: registration.runtime_id,
      runtimeKind: registration.runtime_kind,
      runtimeExpiresAt: registration.expires_at,
    };
    const database = await openBrowserOfflineDatabase();
    try {
      assertCoordinatorIdentityIsCurrent(identity);
      const transaction = database.transaction(OFFLINE_AUTHORIZATION_STORE, "readwrite");
      const completion = idbTransaction(transaction);
      transaction.objectStore(OFFLINE_AUTHORIZATION_STORE).put(record);
      await completion;
      try {
        assertCoordinatorIdentityIsCurrent(identity);
      } catch (error) {
        const cleanupTransaction = database.transaction(OFFLINE_AUTHORIZATION_STORE, "readwrite");
        const cleanupCompletion = idbTransaction(cleanupTransaction);
        cleanupTransaction.objectStore(OFFLINE_AUTHORIZATION_STORE).delete(record.id);
        await cleanupCompletion;
        throw error;
      }
    } finally {
      database.close();
    }
    runtimeClockAnchors.set(id, {
      monotonicMs: record.observedMonotonicMs,
      trustedServerTimeMs,
      wallClockMs: now,
    });
    return payload;
  } catch (error) {
    if (error instanceof BrowserOfflineAuthorizationError) throw error;
    throw new BrowserOfflineAuthorizationError("AUTHORIZATION_INVALID");
  } finally {
    if (timeout !== null) window.clearTimeout(timeout);
  }
}

export async function authorizeBrowserOfflineScan({
  groupId,
  qrPayload,
  sessionId,
}: Readonly<{
  groupId: string;

  qrPayload: string;
  sessionId: string;
}>): Promise<AuthorizedBrowserOfflineScan> {
  const identity = requireCoordinatorIdentity();
  const { payload, record } = await loadAuthorization(identity, groupId);
  const { session, trustedNow } = requireAuthorizationWindow(
    payload,
    record,
    sessionId,
  );
  const tokenHash = await sha256Hex(qrPayload);
  const matches = payload.passengers.filter((candidate) => candidate.token_hash === tokenHash);
  if (matches.length !== 1) {
    throw new BrowserOfflineAuthorizationError("QR_NOT_IN_ACTIVE_ROSTER");
  }
  const passenger = matches[0]!;
  if (trustedNow > requiredInstant(passenger.token_valid_until)) {
    throw new BrowserOfflineAuthorizationError("TOKEN_EVIDENCE_EXPIRED");
  }
  await advanceTrustedHighWater(record, trustedNow);
  return {
    passengerId: passenger.id,
    passengerLabel: passenger.label,
    scannedAt: new Date(trustedNow).toISOString(),
    sessionLabel: session.label,
    trustedServerTimeMs: trustedNow,
    runtimeId: record.runtimeId,
  };
}

/**
 * Verifies locally stored signed readiness without requiring or accepting a QR.
 * This is the same trusted-time and activity-window gate used by queue capture.
 */
export async function checkBrowserOfflineReadiness({
  groupId,
  sessionId,
}: Readonly<{
  groupId: string;
  sessionId: string | null;
}>): Promise<BrowserOfflineReadinessEvidence> {
  const identity = requireCoordinatorIdentity();
  const { payload, record } = await loadAuthorization(identity, groupId);
  const { session, trustedNow } = sessionId === null
    ? requireAuthorizationWindow(payload, record, null)
    : requireAuthorizationWindow(payload, record, sessionId);
  const validUntil = Math.min(
    requiredInstant(payload.expires_at),
    requiredInstant(record.runtimeExpiresAt),
    session ? requiredInstant(session.scheduled_ends_at) : Number.POSITIVE_INFINITY,
  );
  return {
    checkedAt: new Date(trustedNow).toISOString(),
    groupId,
    sessionId,
    validUntil: new Date(validUntil).toISOString(),
  };
}

export async function getBrowserAttendanceRuntimeHint(): Promise<string | null> {
  const identity = requireCoordinatorIdentity();
  const database = await openBrowserOfflineDatabase();
  try {
    const rows = await idbRequest<StoredAuthorization[]>(
      database.transaction(OFFLINE_AUTHORIZATION_STORE, "readonly")
        .objectStore(OFFLINE_AUTHORIZATION_STORE)
        .getAll(),
    );
    const now = Date.now();
    return rows
      .filter((row) => (
        row.ownerUserId === identity.ownerUserId
        && row.agencyId === identity.agencyId
        && UUID.safeParse(row.runtimeId).success
        && requiredInstant(row.runtimeExpiresAt) > now
      ))
      .sort((left, right) => right.runtimeExpiresAt.localeCompare(left.runtimeExpiresAt))[0]
      ?.runtimeId ?? null;
  } finally {
    database.close();
  }
}

export async function loadBrowserOfflineAuthorizationSelections() {
  const identity = requireCoordinatorIdentity();
  const database = await openBrowserOfflineDatabase();
  let rows: StoredAuthorization[];
  try {
    const store = database.transaction(OFFLINE_AUTHORIZATION_STORE, "readonly")
      .objectStore(OFFLINE_AUTHORIZATION_STORE);
    rows = await idbRequest<StoredAuthorization[]>(store.getAll());
  } finally {
    database.close();
  }
  const results: Array<Readonly<{
    groupId: string;
    sessions: BrowserOfflineAuthorizationPayload["sessions"];
  }>> = [];
  for (const row of rows) {
    if (row.ownerUserId !== identity.ownerUserId || row.agencyId !== identity.agencyId) continue;
    try {
      const loaded = await loadAuthorization(identity, row.groupId);
      resolveTrustedTime(loaded.record, loaded.payload);
      results.push({ groupId: row.groupId, sessions: loaded.payload.sessions });
    } catch {
      // Invalid/expired authorization remains unavailable and is never treated
      // as a roster merely because its encrypted row exists.
    }
  }
  return results;
}

export async function purgeAllBrowserOfflineAuthorizations(): Promise<void> {
  runtimeClockAnchors.clear();
  if (typeof indexedDB === "undefined") return;
  const database = await openBrowserOfflineDatabase();
  try {
    const transaction = database.transaction(OFFLINE_AUTHORIZATION_STORE, "readwrite");
    const completion = idbTransaction(transaction);
    transaction.objectStore(OFFLINE_AUTHORIZATION_STORE).clear();
    await completion;
  } finally {
    database.close();
  }
}

async function loadAuthorization(
  identity: Readonly<{ agencyId: string; ownerUserId: string }>,
  groupId: string,
) {
  const id = authorizationId(identity, groupId);
  const database = await openBrowserOfflineDatabase();
  let record: StoredAuthorization | undefined;
  try {
    const store = database.transaction(OFFLINE_AUTHORIZATION_STORE, "readonly")
      .objectStore(OFFLINE_AUTHORIZATION_STORE);
    record = await idbRequest<StoredAuthorization | undefined>(store.get(id));
  } finally {
    database.close();
  }
  if (
    !record
    || record.ownerUserId !== identity.ownerUserId
    || record.agencyId !== identity.agencyId
    || record.groupId !== groupId
    || !UUID.safeParse(record.runtimeId).success
    || !["pwa", "webview"].includes(record.runtimeKind)
    || requiredInstant(record.runtimeExpiresAt) <= Date.now()
  ) {
    throw new BrowserOfflineAuthorizationError("AUTHORIZATION_NOT_AVAILABLE");
  }
  try {
    const value = await unprotectBrowserJson<StoredAuthorizationValue>(
      record.protectedValue,
      authorizationAssociatedData(id),
    );
    const bundle = AuthorizationBundleSchema.parse(value.bundle);
    const payload = await validateAuthorizationBundle(bundle, identity, groupId, false);
    return { payload, record };
  } catch (error) {
    if (error instanceof BrowserOfflineAuthorizationError) throw error;
    throw new BrowserOfflineAuthorizationError("AUTHORIZATION_INVALID");
  }
}

function requireAuthorizationWindow(
  payload: BrowserOfflineAuthorizationPayload,
  record: StoredAuthorization,
  sessionId: string,
): Readonly<{
  session: BrowserOfflineAuthorizationPayload["sessions"][number];
  trustedNow: number;
}>;
function requireAuthorizationWindow(
  payload: BrowserOfflineAuthorizationPayload,
  record: StoredAuthorization,
  sessionId: null,
): Readonly<{ session: null; trustedNow: number }>;
function requireAuthorizationWindow(
  payload: BrowserOfflineAuthorizationPayload,
  record: StoredAuthorization,
  sessionId: string | null,
) {
  const trustedNow = resolveTrustedTime(record, payload);
  const notBefore = requiredInstant(payload.not_before);
  const expiresAt = requiredInstant(payload.expires_at);
  const runtimeExpiresAt = requiredInstant(record.runtimeExpiresAt);
  if (
    trustedNow < notBefore
    || trustedNow > expiresAt
    || trustedNow > runtimeExpiresAt
  ) {
    throw new BrowserOfflineAuthorizationError("AUTHORIZATION_EXPIRED");
  }
  if (sessionId === null) return { session: null, trustedNow };

  const session = payload.sessions.find((candidate) => candidate.id === sessionId);
  if (!session) {
    throw new BrowserOfflineAuthorizationError("ACTIVITY_NOT_AUTHORIZED");
  }
  const startsAt = requiredInstant(session.scheduled_starts_at);
  const endsAt = requiredInstant(session.scheduled_ends_at);
  if (trustedNow < startsAt - ACTIVITY_EARLY_SKEW_MS || trustedNow > endsAt) {
    throw new BrowserOfflineAuthorizationError("ACTIVITY_OUTSIDE_WINDOW");
  }
  return { session, trustedNow };
}

async function validateAuthorizationBundle(
  bundle: BrowserOfflineAuthorizationBundle,
  identity: Readonly<{ agencyId: string; ownerUserId: string }>,
  groupId: string,
  provisionKey: boolean,
) {
  const payloadBytes = decodeBase64url(bundle.payload, MAX_AUTHORIZATION_BYTES);
  const signature = decodeBase64url(bundle.signature, 64);
  const rawPublicKey = decodeBase64url(bundle.public_key, 32);
  if (signature.byteLength !== 64 || rawPublicKey.byteLength !== 32) {
    throw new BrowserOfflineAuthorizationError("AUTHORIZATION_INVALID");
  }
  const verificationKey = provisionKey
    ? await pinVerificationKey(bundle.key_id, rawPublicKey)
    : await loadPinnedVerificationKey(bundle.key_id, rawPublicKey);
  const valid = await crypto.subtle.verify(
    { name: "Ed25519" },
    verificationKey,
    signature,
    payloadBytes,
  );
  if (!valid) throw new BrowserOfflineAuthorizationError("AUTHORIZATION_INVALID");
  const payload = AuthorizationPayloadSchema.parse(
    JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(payloadBytes)),
  );
  if (
    payload.key_id !== bundle.key_id
    || payload.tenant_id !== identity.agencyId
    || payload.coordinator_user_id !== identity.ownerUserId
    || payload.group_id !== groupId
  ) {
    throw new BrowserOfflineAuthorizationError("AUTHORIZATION_INVALID");
  }
  validatePayloadInvariants(payload);
  return payload;
}

function validatePayloadInvariants(payload: BrowserOfflineAuthorizationPayload) {
  const issuedAt = requiredInstant(payload.issued_at);
  const serverTime = requiredInstant(payload.server_time);
  const notBefore = requiredInstant(payload.not_before);
  const expiresAt = requiredInstant(payload.expires_at);
  if (
    issuedAt > serverTime
    || notBefore > serverTime + MAX_CLOCK_ROLLBACK_MS
    || expiresAt <= serverTime
    || expiresAt - serverTime > payload.max_suspension_seconds * 1_000
  ) {
    throw new BrowserOfflineAuthorizationError("AUTHORIZATION_INVALID");
  }
  const sessionIds = new Set<string>();
  for (const session of payload.sessions) {
    if (sessionIds.has(session.id)) throw new BrowserOfflineAuthorizationError("AUTHORIZATION_INVALID");
    sessionIds.add(session.id);
    if (requiredInstant(session.scheduled_ends_at) <= requiredInstant(session.scheduled_starts_at)) {
      throw new BrowserOfflineAuthorizationError("AUTHORIZATION_INVALID");
    }
  }
  const passengerIds = new Set<string>();
  const tokenHashes = new Set<string>();
  for (const passenger of payload.passengers) {
    if (passengerIds.has(passenger.id) || tokenHashes.has(passenger.token_hash)) {
      throw new BrowserOfflineAuthorizationError("AUTHORIZATION_INVALID");
    }
    passengerIds.add(passenger.id);
    tokenHashes.add(passenger.token_hash);
  }
}

function resolveTrustedTime(
  record: StoredAuthorization,
  payload: BrowserOfflineAuthorizationPayload,
) {
  const id = record.id;
  const monotonicNow = performance.now();
  const wallNow = Date.now();

  const runtime = runtimeClockAnchors.get(id);
  let trustedNow: number;
  if (runtime && monotonicNow >= runtime.monotonicMs) {
    const monotonicElapsed = monotonicNow - runtime.monotonicMs;
    const wallElapsed = wallNow - runtime.wallClockMs;
    if (Math.abs(wallElapsed - monotonicElapsed) > MAX_RUNTIME_WALL_DRIFT_MS) {
      throw new BrowserOfflineAuthorizationError("CLOCK_SKEW");
    }
    trustedNow = runtime.trustedServerTimeMs + monotonicElapsed;
  } else {
    const wallElapsed = wallNow - record.observedWallClockMs;
    if (wallElapsed < -MAX_CLOCK_ROLLBACK_MS) {
      throw new BrowserOfflineAuthorizationError("CLOCK_ROLLBACK");
    }
    const maxSuspensionMs = payload.max_suspension_seconds * 1_000;
    if (wallElapsed > maxSuspensionMs) {
      throw new BrowserOfflineAuthorizationError("CLOCK_SKEW");
    }
    trustedNow = Math.max(
      record.trustedHighWaterMs,
      requiredInstant(payload.server_time) + Math.max(0, wallElapsed),
    );
    runtimeClockAnchors.set(id, {
      monotonicMs: monotonicNow,
      trustedServerTimeMs: trustedNow,
      wallClockMs: wallNow,
    });
  }
  return Math.max(record.trustedHighWaterMs, Math.trunc(trustedNow));
}

async function advanceTrustedHighWater(record: StoredAuthorization, trustedNow: number) {
  if (trustedNow <= record.trustedHighWaterMs) return;
  const database = await openBrowserOfflineDatabase();
  try {
    const transaction = database.transaction(OFFLINE_AUTHORIZATION_STORE, "readwrite");
    const completion = idbTransaction(transaction);
    const store = transaction.objectStore(OFFLINE_AUTHORIZATION_STORE);
    const current = await idbRequest<StoredAuthorization | undefined>(store.get(record.id));
    if (
      current
      && current.ownerUserId === record.ownerUserId
      && current.agencyId === record.agencyId
      && current.groupId === record.groupId
      && trustedNow > current.trustedHighWaterMs
    ) {
      store.put({ ...current, trustedHighWaterMs: Math.trunc(trustedNow) });
    }
    await completion;
  } finally {
    database.close();
  }
}

async function pinVerificationKey(keyId: string, rawKey: Uint8Array<ArrayBuffer>) {
  const digest = await sha256HexBytes(rawKey);
  const candidate = await crypto.subtle.importKey(
    "raw",
    rawKey,
    { name: "Ed25519" },
    false,
    ["verify"],
  );
  const id = `offline-verification-key:${keyId}`;
  const database = await openBrowserOfflineDatabase();
  try {
    const transaction = database.transaction(OFFLINE_CRYPTO_KEY_STORE, "readwrite");
    const completion = idbTransaction(transaction);
    const store = transaction.objectStore(OFFLINE_CRYPTO_KEY_STORE);
    const existing = await idbRequest<StoredVerificationKey | undefined>(store.get(id));
    if (existing && existing.digest !== digest) {
      transaction.abort();
      await completion.catch(() => undefined);
      throw new BrowserOfflineAuthorizationError("AUTHORIZATION_INVALID");
    }
    if (!existing) store.add({ id, keyId, digest, key: candidate });
    await completion;
    return existing?.key ?? candidate;
  } finally {
    database.close();
  }
}

async function loadPinnedVerificationKey(
  keyId: string,
  rawKey: Uint8Array<ArrayBuffer>,
) {
  const digest = await sha256HexBytes(rawKey);
  const database = await openBrowserOfflineDatabase();
  try {
    const store = database.transaction(OFFLINE_CRYPTO_KEY_STORE, "readonly")
      .objectStore(OFFLINE_CRYPTO_KEY_STORE);
    const existing = await idbRequest<StoredVerificationKey | undefined>(
      store.get(`offline-verification-key:${keyId}`),
    );
    if (!existing || existing.digest !== digest || existing.key.extractable) {
      throw new BrowserOfflineAuthorizationError("AUTHORIZATION_INVALID");
    }
    return existing.key;
  } finally {
    database.close();
  }
}

function requireCoordinatorIdentity() {
  const { sessionVersion, user } = useAuthStore.getState();
  if (!user?.id || !user.agency_id || user.role !== "agency_coordinator") {
    throw new BrowserOfflineAuthorizationError("AUTHORIZATION_NOT_AVAILABLE");
  }
  return { agencyId: user.agency_id, ownerUserId: user.id, sessionVersion } as const;
}

function assertCoordinatorIdentityIsCurrent(
  identity: Readonly<{ agencyId: string; ownerUserId: string; sessionVersion: number }>,
) {
  const current = requireCoordinatorIdentity();
  if (
    current.agencyId !== identity.agencyId
    || current.ownerUserId !== identity.ownerUserId
    || current.sessionVersion !== identity.sessionVersion
  ) {
    throw new BrowserOfflineAuthorizationError("AUTHORIZATION_NOT_AVAILABLE");
  }
}

function browserRuntimeKind(): "pwa" | "webview" {
  return /(?:^|\s)GlobalConnectsCoordinator\//.test(navigator.userAgent)
    ? "webview"
    : "pwa";
}

function authorizationId(
  identity: Readonly<{ agencyId: string; ownerUserId: string }>,
  groupId: string,
) {
  return JSON.stringify([1, identity.agencyId, identity.ownerUserId, groupId]);
}

function authorizationAssociatedData(id: string) {
  return `coordinator-offline-authorization|${id}`;
}

function requiredInstant(value: string) {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) throw new BrowserOfflineAuthorizationError("AUTHORIZATION_INVALID");
  return parsed;
}

async function sha256Hex(value: string) {
  return sha256HexBytes(new TextEncoder().encode(value));
}

async function sha256HexBytes(value: Uint8Array<ArrayBuffer>) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", value));
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function decodeBase64url(value: string, maxBytes: number): Uint8Array<ArrayBuffer> {
  if (!/^[A-Za-z0-9_-]+$/.test(value) || value.includes("=")) {
    throw new BrowserOfflineAuthorizationError("AUTHORIZATION_INVALID");
  }
  const padding = "=".repeat((4 - value.length % 4) % 4);
  let decoded: string;
  try {
    decoded = window.atob(value.replace(/-/g, "+").replace(/_/g, "/") + padding);
  } catch {
    throw new BrowserOfflineAuthorizationError("AUTHORIZATION_INVALID");
  }
  if (decoded.length === 0 || decoded.length > maxBytes) {
    throw new BrowserOfflineAuthorizationError("AUTHORIZATION_INVALID");
  }
  return Uint8Array.from(decoded, (character) => character.charCodeAt(0));
}
