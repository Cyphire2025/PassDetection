import { createHash, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";
import { attendanceTestDatabase } from "./attendance-database.ts";

export const OWNER = "10000000-0000-4000-8000-000000000001";
export const OTHER = "10000000-0000-4000-8000-000000000002";
export const GROUP = "20000000-0000-4000-8000-000000000001";
export const SESSION = "30000000-0000-4000-8000-000000000001";
export const RUNTIME = "40000000-0000-4000-8000-000000000001";
export const PASSENGER = "60000000-0000-4000-8000-000000000001";
export const SECOND_SESSION = "30000000-0000-4000-8000-000000000002";
export const QR = `pdatt:${"A".repeat(43)}`;
export const PENDING_STORE = "pending-attendance-scans";
const TENANT = "50000000-0000-4000-8000-000000000001";
export const OWNER_KEY = "passdetection:session-owner";
const STORAGE_KEY = "coordinator-offline-aes-gcm-v1";
export const AUTH_STORE = "coordinator-offline-authorizations";
export const KEY_STORE = "offline-crypto-keys";
const source = readFileSync(new URL("../../../public/offline-scanner.js", import.meta.url), "utf8");
const html = readFileSync(new URL("../../../public/offline.html", import.meta.url), "utf8");

async function signedStorage({ corrupt = false, closedSession = false, extraSession = false } = {}) {
  const database = attendanceTestDatabase();
  const now = Date.now(), instant = offset => new Date(now + offset).toISOString();
  const keys = await webcrypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
  const publicBytes = new Uint8Array(await webcrypto.subtle.exportKey("raw", keys.publicKey));
  const pinned = await webcrypto.subtle.importKey("raw", publicBytes, { name: "Ed25519" }, false, ["verify"]);
  const key = await webcrypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  const payload = { schema_version: 1, key_id: "synthetic-key", coordinator_user_id: OWNER, tenant_id: TENANT,
    group_id: GROUP, group_label: "Synthetic private trip A", server_time: instant(0), issued_at: instant(0),
    not_before: instant(-60000), expires_at: instant(3600000), max_suspension_seconds: 3600,
    sessions: [{ id: SESSION, label: "Synthetic private activity A", status: "active", scheduled_starts_at: instant(-120000), scheduled_ends_at: instant(closedSession ? -60000 : 3600000) },
      ...(extraSession ? [{ id: SECOND_SESSION, label: "Synthetic second activity", status: "active", scheduled_starts_at: instant(-120000), scheduled_ends_at: instant(3600000) }] : [])],
    passengers: [{ id: PASSENGER, label: "Synthetic traveller A", token_hash: createHash("sha256").update(QR).digest("hex"), token_valid_until: instant(3600000) }] };
  const bytes = new TextEncoder().encode(JSON.stringify(payload));
  const signature = new Uint8Array(await webcrypto.subtle.sign({ name: "Ed25519" }, keys.privateKey, bytes));
  if (corrupt) signature[0] ^= 1;
  const bundle = { key_id: payload.key_id, payload: Buffer.from(bytes).toString("base64url"),
    signature: Buffer.from(signature).toString("base64url"), public_key: Buffer.from(publicBytes).toString("base64url") };
  const id = `synthetic:${OWNER}:${GROUP}`, iv = webcrypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await webcrypto.subtle.encrypt({ name: "AES-GCM", iv, tagLength: 128,
    additionalData: new TextEncoder().encode(`coordinator-offline-authorization|${id}`) }, key,
  new TextEncoder().encode(JSON.stringify({ bundle, payload })));
  database.rows(AUTH_STORE).set(id, { id, ownerUserId: OWNER, agencyId: TENANT, groupId: GROUP,
    runtimeId: RUNTIME, runtimeKind: "pwa", runtimeExpiresAt: instant(3600000), observedWallClockMs: now, trustedHighWaterMs: now,
    protectedValue: { version: 1, algorithm: "AES-GCM", keyId: STORAGE_KEY, iv, ciphertext } });
  database.rows(KEY_STORE).set(STORAGE_KEY, { id: STORAGE_KEY, key });
  const pinnedId = `offline-verification-key:${payload.key_id}`;
  database.rows(KEY_STORE).set(pinnedId, { id: pinnedId, key: pinned, digest: createHash("sha256").update(publicBytes).digest("hex") });
  return database;
}

export async function startup({ initialOwner = OWNER, corrupt = false, closedSession = false, extraSession = false, seedStorage } = {}) {
  const storage = await signedStorage({ corrupt, closedSession, extraSession });
  seedStorage?.(storage);
  const dom = new JSDOM(html, { url: `https://offline-fixture.example.test/coordinator/groups/${GROUP}/scanner?sessionId=${SESSION}`, runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom;
  let holdReads = false;
  const pendingReads = [];
  const transaction = storage.database.transaction.bind(storage.database);
  storage.database.transaction = (...args) => {
    const result = transaction(...args);
    const objectStore = result.objectStore.bind(result);
    result.objectStore = (name) => {
      const store = objectStore(name);
      if (name !== PENDING_STORE) return store;
      const index = store.index.bind(store);
      store.index = (...keys) => {
        const value = index(...keys);
        return { ...value, count(owner) {
          const request = { result: undefined, onsuccess: null };
          queueMicrotask(() => {
            request.result = [...storage.rows(name).values()].filter(row => row.ownerUserId === owner).length;
            request.onsuccess?.();
          });
          return request;
        }, getAll(owner) {
          if (!holdReads) return value.getAll(owner);
          const request = { result: [...storage.rows(name).values()].filter(row => row.ownerUserId === owner), onsuccess: null };
          pendingReads.push((error) => {
            if (error) { request.error = error; request.onerror?.(); }
            else request.onsuccess?.();
          });
          return request;
        } };
      };
      return store;
    };
    return result;
  };
  const entered = Promise.withResolvers(), release = Promise.withResolvers();
  const encryptEntered = Promise.withResolvers(), encryptRelease = Promise.withResolvers();
  let holdEncryption = false;
  const subtle = new Proxy(webcrypto.subtle, { get(target, key) {
    if (key === "verify") return async (...args) => {
      const result = await target.verify(...args);
      entered.resolve(result); await release.promise; return result;
    };
    if (key === "encrypt") return async (...args) => {
      const result = await target.encrypt(...args);
      if (holdEncryption) {
        encryptEntered.resolve(); await encryptRelease.promise;
      }
      return result;
    };
    const value = Reflect.get(target, key);
    return typeof value === "function" ? value.bind(target) : value;
  } });
  Object.defineProperty(window, "crypto", { value: { subtle, getRandomValues: webcrypto.getRandomValues.bind(webcrypto), randomUUID: webcrypto.randomUUID.bind(webcrypto) } });
  Object.defineProperty(window, "indexedDB", { value: { open() {
    const request = { result: storage.database, onsuccess: null };
    queueMicrotask(() => request.onsuccess?.()); return request;
  } } });
  for (const [name, value] of Object.entries({ TextEncoder, TextDecoder, ArrayBuffer, Uint8Array })) Object.defineProperty(window, name, { value });
  window.localStorage.setItem(OWNER_KEY, initialOwner);
  // No signatures, initialization, plaintext, or production functions are replaced.
  // Native crypto completes before the test-only scheduling gate is held.
  window.eval(source);
  return { window, storage, pendingReads, holdPendingReads() { holdReads = true; },
    holdPendingEncryption() { holdEncryption = true; }, encryptEntered: encryptEntered.promise,
    releaseEncryption: () => encryptRelease.resolve(), entered: entered.promise,
    release: () => release.resolve(), close: () => window.close() };
}
export async function waitUntil(condition) {
  for (let attempt = 0; attempt < 200; attempt++) {
    if (condition()) return;
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  throw new Error("Synthetic offline startup did not settle");
}
export async function settled(context) {
  await waitUntil(() => !context.window.document.getElementById("offline-scanner").hidden || !context.window.document.getElementById("offline-unavailable").hidden);
}

