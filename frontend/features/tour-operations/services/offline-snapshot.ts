import { useEffect, useState } from "react";

import { useAuthStore } from "@/stores/auth.store";

import { protectBrowserJson, unprotectBrowserJson, type ProtectedBrowserValue } from "./browser-offline-crypto";
import {
  OFFLINE_SNAPSHOT_STORE,
  OWNER_USER_ID_INDEX,
  idbRequest,
  idbTransaction,
  openBrowserOfflineDatabase,
} from "./browser-offline-database";

const SNAPSHOT_SCHEMA_VERSION = 2;
const SNAPSHOT_EVENT = "passdetection:coordinator-offline-snapshot-changed";
const DEFAULT_SNAPSHOT_TTL_MS = 72 * 60 * 60_000;
const MAX_SNAPSHOT_TTL_MS = 14 * 24 * 60 * 60_000;

type SnapshotEnvelope = Readonly<{
  expiresAt: string;
  issuedAt: string;
  payload: unknown;
  schemaVersion: typeof SNAPSHOT_SCHEMA_VERSION;
}>;

type StoredSnapshot = Readonly<{
  agencyId: string;
  expiresAt: string;
  id: string;
  issuedAt: string;
  key: string;
  ownerUserId: string;
  protectedValue: ProtectedBrowserValue;
  schemaVersion: typeof SNAPSHOT_SCHEMA_VERSION;
}>;

type SnapshotIdentity = Readonly<{
  agencyId: string;
  ownerUserId: string;
  sessionVersion: number;
}>;

export type OfflineSnapshotWriteOptions = Readonly<{
  expiresAt?: string;
}>;

export const offlineSnapshotKeys = {
  myGroups: "passdetection-tour-ops-my-groups",
  myPassengers: (groupId: string) => `passdetection-tour-ops-my-passengers:${groupId}`,
  mySessions: (groupId: string) => `passdetection-tour-ops-my-sessions:${groupId}`,
};

/**
 * Loads an encrypted, account-and-tenant-scoped snapshot. A valid v1
 * localStorage value is copied into v2, decrypted/verified, and only then
 * removed. Invalid or unavailable legacy data is left untouched for explicit
 * recovery; attendance queue stores are never part of snapshot cleanup.
 */
export async function readOfflineSnapshot<T>(key: string, fallback: T): Promise<T> {
  if (typeof window === "undefined") return fallback;
  const identity = currentSnapshotIdentity();
  if (!identity) return fallback;
  await purgeExpiredCoordinatorOfflineSnapshots().catch(() => undefined);
  const existing = await readStoredSnapshot<T>(identity, key);
  if (existing !== null) return existing;
  return migrateLegacySnapshot(identity, key, fallback);
}

export async function writeOfflineSnapshot(
  key: string,
  value: unknown,
  options: OfflineSnapshotWriteOptions = {},
): Promise<void> {
  if (typeof window === "undefined") return;
  const identity = currentSnapshotIdentity();
  if (!identity) return;
  const now = Date.now();
  const expiresAtMs = resolveOfflineSnapshotExpiry(now, options.expiresAt);
  if (expiresAtMs <= now) {
    await removeSnapshot(identity, key);
    return;
  }
  const issuedAt = new Date(now).toISOString();
  const expiresAt = new Date(expiresAtMs).toISOString();
  const payload = minimizeOfflineSnapshotForStorage(key, value);
  const envelope: SnapshotEnvelope = {
    expiresAt,
    issuedAt,
    payload,
    schemaVersion: SNAPSHOT_SCHEMA_VERSION,
  };
  const id = snapshotId(identity, key);
  const associatedData = snapshotAssociatedData(id);
  const protectedValue = await protectBrowserJson(envelope, associatedData);
  if (!snapshotIdentityIsCurrent(identity)) return;
  const record: StoredSnapshot = {
    agencyId: identity.agencyId,
    expiresAt,
    id,
    issuedAt,
    key,
    ownerUserId: identity.ownerUserId,
    protectedValue,
    schemaVersion: SNAPSHOT_SCHEMA_VERSION,
  };
  const database = await openBrowserOfflineDatabase();
  try {
    if (!snapshotIdentityIsCurrent(identity)) return;
    const transaction = database.transaction(OFFLINE_SNAPSHOT_STORE, "readwrite");
    const completion = idbTransaction(transaction);
    transaction.objectStore(OFFLINE_SNAPSHOT_STORE).put(record);
    await completion;
    if (!snapshotIdentityIsCurrent(identity)) {
      const cleanupTransaction = database.transaction(OFFLINE_SNAPSHOT_STORE, "readwrite");
      const cleanupCompletion = idbTransaction(cleanupTransaction);
      cleanupTransaction.objectStore(OFFLINE_SNAPSHOT_STORE).delete(record.id);
      await cleanupCompletion;
      return;
    }
  } finally {
    database.close();
  }
  announceSnapshotChanged(key);
}

export function useOfflineSnapshot<T>(key: string, fallback: T): T {
  const ownerUserId = useAuthStore((state) => state.user?.id ?? null);
  const agencyId = useAuthStore((state) => state.user?.agency_id ?? null);
  const scope = `${agencyId ?? "anonymous"}:${ownerUserId ?? "anonymous"}:${key}`;
  const [snapshot, setSnapshot] = useState<Readonly<{ scope: string; value: T }> | null>(null);
  const value = snapshot?.scope === scope ? snapshot.value : fallback;

  useEffect(() => {
    let cancelled = false;
    if (!ownerUserId || !agencyId) return () => undefined;
    const load = () => {
      void readOfflineSnapshot(key, fallback).then((next) => {
        if (!cancelled) setSnapshot({ scope, value: next });
      }).catch(() => {
        if (!cancelled) setSnapshot({ scope, value: fallback });
      });
    };
    const handleChange = (event: Event) => {
      const changedKey = (event as CustomEvent<{ key?: string }>).detail?.key;
      if (!changedKey || changedKey === key) load();
    };
    load();
    window.addEventListener(SNAPSHOT_EVENT, handleChange);
    const cleanupTimer = window.setInterval(
      () => void purgeExpiredCoordinatorOfflineSnapshots().catch(() => undefined),
      15 * 60_000,
    );
    return () => {
      cancelled = true;
      window.clearInterval(cleanupTimer);
      window.removeEventListener(SNAPSHOT_EVENT, handleChange);
    };
  }, [agencyId, fallback, key, ownerUserId, scope]);

  return value;
}

export async function purgeExpiredCoordinatorOfflineSnapshots(now = Date.now()): Promise<number> {
  if (typeof indexedDB === "undefined") return 0;
  const database = await openBrowserOfflineDatabase();
  try {
    const transaction = database.transaction(OFFLINE_SNAPSHOT_STORE, "readwrite");
    const completion = idbTransaction(transaction);
    const store = transaction.objectStore(OFFLINE_SNAPSHOT_STORE);
    const records = await idbRequest<StoredSnapshot[]>(store.getAll());
    let removed = 0;
    for (const record of records) {
      const expiresAt = Date.parse(record.expiresAt);
      if (!Number.isFinite(expiresAt) || expiresAt <= now) {
        store.delete(record.id);
        removed += 1;
      }
    }
    await completion;
    if (removed > 0) announceSnapshotChanged();
    return removed;
  } finally {
    database.close();
  }
}

export async function purgeAllCoordinatorOfflineSnapshots(): Promise<void> {
  if (typeof indexedDB === "undefined") return;
  const database = await openBrowserOfflineDatabase();
  try {
    const transaction = database.transaction(OFFLINE_SNAPSHOT_STORE, "readwrite");
    const completion = idbTransaction(transaction);
    transaction.objectStore(OFFLINE_SNAPSHOT_STORE).clear();
    await completion;
  } finally {
    database.close();
  }
  announceSnapshotChanged();
}

async function readStoredSnapshot<T>(
  identity: SnapshotIdentity,
  key: string,
): Promise<T | null> {
  const id = snapshotId(identity, key);
  const database = await openBrowserOfflineDatabase();
  let record: StoredSnapshot | undefined;
  try {
    const store = database.transaction(OFFLINE_SNAPSHOT_STORE, "readonly")
      .objectStore(OFFLINE_SNAPSHOT_STORE);
    record = await idbRequest<StoredSnapshot | undefined>(store.get(id));
  } finally {
    database.close();
  }
  if (!record) return null;
  if (
    record.schemaVersion !== SNAPSHOT_SCHEMA_VERSION
    || record.ownerUserId !== identity.ownerUserId
    || record.agencyId !== identity.agencyId
    || record.key !== key
  ) {
    return null;
  }
  const expiresAt = Date.parse(record.expiresAt);
  if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
    await removeSnapshot(identity, key);
    return null;
  }
  try {
    const envelope = await unprotectBrowserJson<SnapshotEnvelope>(
      record.protectedValue,
      snapshotAssociatedData(id),
    );
    if (
      envelope.schemaVersion !== SNAPSHOT_SCHEMA_VERSION
      || envelope.expiresAt !== record.expiresAt
      || envelope.issuedAt !== record.issuedAt
    ) {
      return null;
    }
    return rehydrateSnapshotPayload(key, envelope.payload) as T;
  } catch {
    // Corrupt ciphertext is not returned or silently deleted. Keeping it makes
    // the failure observable and prevents a cleanup race from touching queues.
    return null;
  }
}

async function migrateLegacySnapshot<T>(
  identity: SnapshotIdentity,
  key: string,
  fallback: T,
): Promise<T> {
  const legacyKey = `${key}:user:${identity.ownerUserId}`;
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(legacyKey);
  } catch {
    return fallback;
  }
  if (!raw) return fallback;
  try {
    const parsed = JSON.parse(raw) as unknown;
    await writeOfflineSnapshot(key, parsed);
    const verified = await readStoredSnapshot<T>(identity, key);
    if (verified === null) return fallback;
    window.localStorage.removeItem(legacyKey);
    return verified;
  } catch {
    // Preserve the legacy value if parsing, encryption, quota, or verification
    // fails. A later healthy runtime can retry without losing coordination data.
    return fallback;
  }
}

async function removeSnapshot(
  identity: SnapshotIdentity,
  key: string,
) {
  const database = await openBrowserOfflineDatabase();
  try {
    const transaction = database.transaction(OFFLINE_SNAPSHOT_STORE, "readwrite");
    const completion = idbTransaction(transaction);
    transaction.objectStore(OFFLINE_SNAPSHOT_STORE).delete(snapshotId(identity, key));
    await completion;
  } finally {
    database.close();
  }
  announceSnapshotChanged(key);
}

function currentSnapshotIdentity() {
  const { sessionVersion, user } = useAuthStore.getState();
  if (!user?.id || !user.agency_id || user.role !== "agency_coordinator") return null;
  return { agencyId: user.agency_id, ownerUserId: user.id, sessionVersion } as const;
}

function snapshotIdentityIsCurrent(
  identity: SnapshotIdentity,
) {
  const current = currentSnapshotIdentity();
  return current?.agencyId === identity.agencyId
    && current.ownerUserId === identity.ownerUserId
    && current.sessionVersion === identity.sessionVersion;
}

function snapshotId(
  identity: Readonly<{ agencyId: string; ownerUserId: string }>,
  key: string,
) {
  return JSON.stringify([SNAPSHOT_SCHEMA_VERSION, identity.agencyId, identity.ownerUserId, key]);
}

function snapshotAssociatedData(id: string) {
  return `coordinator-offline-snapshot|${id}`;
}

export function resolveOfflineSnapshotExpiry(now: number, requested?: string): number {
  const requestedExpiry = requested ? Date.parse(requested) : Number.NaN;
  return Number.isFinite(requestedExpiry)
    ? Math.min(requestedExpiry, now + MAX_SNAPSHOT_TTL_MS)
    : now + DEFAULT_SNAPSHOT_TTL_MS;
}

export function minimizeOfflineSnapshotForStorage(key: string, value: unknown): unknown {
  if (!Array.isArray(value)) return [];
  if (key === offlineSnapshotKeys.myGroups) {
    return value.flatMap((candidate) => {
      const row = recordValue(candidate);
      if (!row || !stringValue(row.id) || !stringValue(row.name)) return [];
      return [{
        id: row.id,
        name: row.name,
        status: stringValue(row.status) ?? "unknown",
        destination: optionalString(row.destination),
        travel_date: optionalString(row.travel_date),
        departure_cities: stringArray(row.departure_cities, 30),
        base_city_enabled: row.base_city_enabled === true,
        nearest_international_airport_enabled: row.nearest_international_airport_enabled === true,
        staff_code_enabled: row.staff_code_enabled === true,
        agent_employee_code_enabled: row.agent_employee_code_enabled === true,
        meal_preference_enabled: row.meal_preference_enabled === true,
        passenger_count: safeNonnegativeInteger(row.passenger_count),
        assigned_passengers_count: safeNonnegativeInteger(row.assigned_passengers_count),
        unassigned_passengers_count: safeNonnegativeInteger(row.unassigned_passengers_count),
      }];
    });
  }
  if (key.startsWith("passdetection-tour-ops-my-passengers:")) {
    return value.flatMap((candidate) => {
      const row = recordValue(candidate);
      if (!row || !stringValue(row.id) || !stringValue(row.client_name)) return [];
      return [{
        id: row.id,
        client_name: row.client_name,
        departure_city: optionalString(row.departure_city),
        status: stringValue(row.status) ?? "unknown",
      }];
    });
  }
  if (key.startsWith("passdetection-tour-ops-my-sessions:")) {
    return value.flatMap((candidate) => {
      const row = recordValue(candidate);
      if (!row || !stringValue(row.id) || !stringValue(row.group_id) || !stringValue(row.name)) {
        return [];
      }
      return [{
        id: row.id,
        group_id: row.group_id,
        name: row.name,
        status: stringValue(row.status) ?? "unknown",
        created_at: optionalString(row.created_at) ?? new Date(0).toISOString(),
        started_at: optionalString(row.started_at),
        completed_at: optionalString(row.completed_at),
        scanned_count: safeNonnegativeInteger(row.scanned_count),
        assigned_count: safeNonnegativeInteger(row.assigned_count),
      }];
    });
  }
  return [];
}

function rehydrateSnapshotPayload(key: string, value: unknown): unknown {
  if (!Array.isArray(value)) return [];
  if (key === offlineSnapshotKeys.myGroups) {
    return value.map((candidate) => ({ ...recordValue(candidate), coordinators: [] }));
  }
  if (key.startsWith("passdetection-tour-ops-my-passengers:")) {
    return value.map((candidate) => ({
      ...recordValue(candidate),
      client_email: null,
      client_phone: null,
      coordinator_id: null,
      coordinator_name: null,
    }));
  }
  return value;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function stringArray(value: unknown, limit: number): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string").slice(0, limit)
    : [];
}

function safeNonnegativeInteger(value: unknown): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : 0;
}

function announceSnapshotChanged(key?: string) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(SNAPSHOT_EVENT, { detail: { key } }));
}

export async function listCurrentOwnerSnapshotKeys(): Promise<string[]> {
  const identity = currentSnapshotIdentity();
  if (!identity) return [];
  const database = await openBrowserOfflineDatabase();
  try {
    const store = database.transaction(OFFLINE_SNAPSHOT_STORE, "readonly")
      .objectStore(OFFLINE_SNAPSHOT_STORE);
    const rows = await idbRequest<StoredSnapshot[]>(
      store.index(OWNER_USER_ID_INDEX).getAll(identity.ownerUserId),
    );
    return rows
      .filter((row) => row.agencyId === identity.agencyId)
      .map((row) => row.key);
  } finally {
    database.close();
  }
}
