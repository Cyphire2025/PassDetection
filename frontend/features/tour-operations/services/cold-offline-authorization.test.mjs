import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import test from "node:test";
import { startup, settled, waitUntil, QR, OWNER, OTHER, OWNER_KEY, GROUP, SESSION, RUNTIME, PASSENGER,
  AUTH_STORE, KEY_STORE, PENDING_STORE } from "../test-support/cold-offline.test-fixture.mjs";

async function readyCamera(options) {
  const context = await startup(options);
  await context.entered; context.release(); await settled(context);
  let decode;
  Object.defineProperty(context.window, "isSecureContext", { value: true });
  Object.defineProperty(context.window.navigator, "mediaDevices", { value: { getUserMedia() {} } });
  context.window.ZXingBrowser = { BrowserQRCodeReader: class {
    async decodeFromConstraints(_constraints, _video, callback) {
      decode = callback;
      return { stop() {} };
    }
  } };
  context.window.document.getElementById("start-camera").click();
  await waitUntil(() => Boolean(decode));
  await waitUntil(() => context.window.document.getElementById("scan-feedback").textContent.startsWith("Camera ready"));
  return { ...context, decode: (value) => decode({ getText: () => value }) };
}

const feedback = (context) => context.window.document.getElementById("scan-feedback").textContent;

test("cold-offline scan context retains the verified installation runtime for queue metadata", async () => {
  const context = await readyCamera();
  try {
    let persisted = 0;
    context.storage.onWrite((store) => { if (store === AUTH_STORE) persisted++; });
    context.decode(QR);
    await waitUntil(() => feedback(context).startsWith("Saved offline"));
    const rows = [...context.storage.rows(PENDING_STORE).values()];
    assert.equal(rows.length, 1);
    const row = rows[0];
    assert.equal(row.runtimeId, RUNTIME);
    assert.equal(row.deviceId, RUNTIME);
    assert.equal(row.ownerUserId, OWNER);
    assert.equal(row.groupId, GROUP);
    assert.equal(row.sessionId, SESSION);
    assert.equal(row.storageVersion, 5);
    assert.equal(row.deliveryState, "pending");
    assert.equal(persisted, 1);
    assert.doesNotMatch(JSON.stringify(row), /pdatt:|Synthetic traveller A/);
    const key = context.storage.rows(KEY_STORE).get("coordinator-offline-aes-gcm-v1").key;
    assert.equal(key.extractable, false);
    const plaintext = await webcrypto.subtle.decrypt({ name: "AES-GCM", tagLength: 128,
      iv: row.protectedQrPayload.iv,
      additionalData: new TextEncoder().encode(JSON.stringify(["attendance-pending-v5", row.id, OWNER, GROUP, SESSION])),
    }, key, row.protectedQrPayload.ciphertext);
    assert.deepEqual(JSON.parse(new TextDecoder().decode(plaintext)), {
      qrPayload: QR, recovery: { passengerId: PASSENGER, passengerLabel: "Synthetic traveller A", sessionLabel: "Synthetic private activity A" },
    });
    context.decode(QR);
    assert.match(feedback(context), /Already read this QR/);
    assert.equal(context.storage.rows(PENDING_STORE).size, 1);
  } finally { context.release(); context.close(); }
});

test("a different QR cannot produce an authorized scan context", async () => {
  const context = await readyCamera();
  try {
    let persisted = 0;
    context.storage.onWrite((store) => { if (store === AUTH_STORE) persisted++; });
    context.decode(`pdatt:${"B".repeat(43)}`);
    await waitUntil(() => feedback(context).includes("Wrong group or unauthorized passenger"));
    assert.equal(context.storage.rows(PENDING_STORE).size, 0);
    assert.equal(persisted, 0);
  } finally { context.release(); context.close(); }
});

test("a closed signed activity cannot produce an authorized scan context", async () => {
  const context = await readyCamera({ closedSession: true });
  try {
    let persisted = 0;
    context.storage.onWrite((store) => { if (store === AUTH_STORE) persisted++; });
    context.decode(QR);
    await waitUntil(() => feedback(context).includes("not yet valid, or closed"));
    assert.equal(context.storage.rows(PENDING_STORE).size, 0);
    assert.equal(persisted, 0);
  } finally { context.release(); context.close(); }
});

test("the standalone queue refuses a new scan at its existing owner capacity", async () => {
  const context = await readyCamera();
  try {
    for (let i = 0; i < 5000; i++) {
      context.storage.rows(PENDING_STORE).set(String(i), { id: String(i), ownerUserId: OWNER });
    }
    context.decode(QR);
    await waitUntil(() => feedback(context).includes("storage is full"));
    assert.equal(context.storage.rows(PENDING_STORE).size, 5000);
  } finally { context.release(); context.close(); }
});

test("native encryption already in flight cannot recreate the previous owner's cleared queue", async () => {
  const context = await readyCamera();
  try {
    context.holdPendingEncryption(); context.decode(QR);
    await context.encryptEntered;
    context.window.localStorage.setItem(OWNER_KEY, OTHER);
    context.window.dispatchEvent(new context.window.StorageEvent("storage", { key: OWNER_KEY, oldValue: OWNER, newValue: OTHER }));
    context.storage.rows(PENDING_STORE).clear();
    context.storage.rows(AUTH_STORE).clear();
    context.storage.rows(KEY_STORE).clear();
    context.releaseEncryption();
    await waitUntil(() => /Could not protect|Saved offline/.test(feedback(context)));
    assert.equal(context.window.document.getElementById("offline-scanner").hidden, true);
    assert.equal(context.storage.rows(PENDING_STORE).size, 0);
  } finally { context.releaseEncryption(); context.release(); context.close(); }
});

test("same-owner refresh during native encryption preserves the legitimate pending scan", async () => {
  const context = await readyCamera();
  try {
    context.holdPendingEncryption(); context.decode(QR);
    await context.encryptEntered;
    context.window.dispatchEvent(new context.window.StorageEvent("storage", { key: OWNER_KEY, oldValue: OWNER, newValue: OWNER }));
    context.releaseEncryption();
    await waitUntil(() => feedback(context).startsWith("Saved offline"));
    assert.equal(context.storage.rows(PENDING_STORE).size, 1);
    assert.equal(context.window.document.getElementById("offline-scanner").hidden, false);
  } finally { context.releaseEncryption(); context.release(); context.close(); }
});

