import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import test from "node:test";
import { startup, settled, QR, OWNER, GROUP, SESSION, RUNTIME, PENDING_STORE,
  KEY_STORE } from "../test-support/cold-offline.test-fixture.mjs";

const legacy = () => ({ id: "synthetic-legacy-pending", ownerUserId: OWNER, groupId: GROUP,
  sessionId: SESSION, qrPayload: QR, clientEventId: "synthetic-client-event", deviceId: RUNTIME,
  scannedAt: "2026-10-30T10:00:00Z", queuedAt: "2026-10-30T10:00:00Z" });

test("standalone startup protects a valid legacy pending row without changing its scan identity", async () => {
  const context = await startup({ seedStorage(storage) {
    const row = legacy(); storage.rows(PENDING_STORE).set(row.id, row);
  } });
  try {
    await context.entered; context.release(); await settled(context);
    const rows = [...context.storage.rows(PENDING_STORE).values()];
    assert.equal(rows.length, 1);
    const row = rows[0];
    assert.equal(row.storageVersion, 5);
    assert.equal(row.ownerUserId, OWNER);
    assert.equal(row.clientEventId, "synthetic-client-event");
    assert.match(row.scanReference, /^sha256:[0-9a-f]{64}$/);
    assert.equal(row.id, `attendance-scan:${row.scanReference}`);
    assert.equal(context.storage.rows(PENDING_STORE).has("synthetic-legacy-pending"), false);
    assert.equal("qrPayload" in row, false);
    const key = context.storage.rows(KEY_STORE).get("coordinator-offline-aes-gcm-v1").key;
    const bytes = await webcrypto.subtle.decrypt({ name: "AES-GCM", tagLength: 128,
      iv: row.protectedQrPayload.iv,
      additionalData: new TextEncoder().encode(JSON.stringify(["attendance-pending-v5", row.id, OWNER, GROUP, SESSION])),
    }, key, row.protectedQrPayload.ciphertext);
    assert.deepEqual(JSON.parse(new TextDecoder().decode(bytes)), { qrPayload: QR });
  } finally { context.release(); context.close(); }
});

test("unattributable legacy rows remain quarantined for online reconciliation", async () => {
  const row = { id: "synthetic-unscoped-row", qrPayload: QR };
  const context = await startup({ seedStorage(storage) { storage.rows(PENDING_STORE).set(row.id, row); } });
  try {
    await context.entered; context.release(); await settled(context);
    assert.deepEqual(context.storage.rows(PENDING_STORE).get(row.id), row);
    assert.equal(context.storage.rows(PENDING_STORE).size, 1);
  } finally { context.release(); context.close(); }
});

test("legacy terminal metadata is sanitized without dropping its reconciliation record", async () => {
  const store = "rejected-attendance-scans";
  const context = await startup({ seedStorage(storage) {
    storage.rows(store).set("synthetic-rejected", { ...legacy(), id: "synthetic-rejected",
      rejectedAt: "2026-10-30T10:01:00Z", errorCode: "SYNTHETIC_TERMINAL", passengerLabel: "Synthetic private legacy label" });
  } });
  try {
    await context.entered; context.release(); await settled(context);
    const rows = [...context.storage.rows(store).values()];
    assert.equal(rows.length, 1);
    assert.match(rows[0].id, /^attendance-rejected:sha256:/);
    assert.equal(rows[0].errorCode, "SYNTHETIC_TERMINAL");
    assert.equal(rows[0].ownerUserId, OWNER);
    assert.equal(rows[0].clientEventId, "synthetic-client-event");
    assert.equal("qrPayload" in rows[0], false);
    assert.equal("passengerLabel" in rows[0], false);
  } finally { context.release(); context.close(); }
});
