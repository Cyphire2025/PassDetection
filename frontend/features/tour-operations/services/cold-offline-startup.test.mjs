import assert from "node:assert/strict";
import test from "node:test";
import { startup, settled, waitUntil, OWNER, OTHER, OWNER_KEY, AUTH_STORE, KEY_STORE,
  GROUP, SESSION, SECOND_SESSION, PENDING_STORE } from "../test-support/cold-offline.test-fixture.mjs";

test("normal standalone startup verifies native signed/encrypted readiness for its current owner", async () => {
  const context = await startup();
  try {
    assert.equal(await context.entered, true); context.release(); await settled(context);
    assert.equal(context.window.document.getElementById("offline-scanner").hidden, false);
    assert.equal(context.window.document.getElementById("group-select").textContent, "Synthetic private trip A");
    assert.match(context.window.document.getElementById("session-select").textContent, /Synthetic private activity A/);
  } finally { context.release(); context.close(); }
});

test("another owner at initial load cannot publish the first owner's cached readiness", async () => {
  const context = await startup({ initialOwner: OTHER });
  try {
    context.release(); await settled(context);
    assert.equal(context.window.document.getElementById("offline-scanner").hidden, true);
    assert.doesNotMatch(context.window.document.body.textContent, /Synthetic private trip A|Synthetic private activity A/);
  } finally { context.release(); context.close(); }
});

test("an owner change while native verification is pending cannot publish the old owner's private options", async () => {
  const context = await startup();
  try {
    assert.equal(await context.entered, true);
    context.window.localStorage.setItem(OWNER_KEY, OTHER);
    context.window.dispatchEvent(new context.window.StorageEvent("storage", { key: OWNER_KEY, oldValue: OWNER, newValue: OTHER }));
    // The verified CryptoKeys are already in flight: central persisted-state purge
    // cannot revoke those JavaScript handles or substitute the missing UI fence.
    context.storage.rows(AUTH_STORE).clear(); context.storage.rows(KEY_STORE).clear();
    context.release(); await settled(context);
    assert.equal(context.window.document.getElementById("offline-scanner").hidden, true);
    assert.doesNotMatch(context.window.document.body.textContent, /Synthetic private trip A|Synthetic private activity A/);
  } finally { context.release(); context.close(); }
});

test("a native signature failure keeps the standalone private scanner unavailable", async () => {
  const context = await startup({ corrupt: true });
  try {
    assert.equal(await context.entered, false); context.release(); await settled(context);
    assert.equal(context.window.document.getElementById("offline-scanner").hidden, true);
    assert.doesNotMatch(context.window.document.body.textContent, /Synthetic private trip A|Synthetic private activity A/);
  } finally { context.release(); context.close(); }
});

test("a same-owner storage refresh while verifying preserves the signed startup", async () => {
  const context = await startup();
  try {
    assert.equal(await context.entered, true);
    context.window.localStorage.setItem(OWNER_KEY, OWNER);
    context.window.dispatchEvent(new context.window.StorageEvent("storage", { key: OWNER_KEY, oldValue: OWNER, newValue: OWNER }));
    context.release(); await settled(context);
    assert.equal(context.window.document.getElementById("offline-scanner").hidden, false);
    assert.equal(context.window.document.getElementById("group-select").textContent, "Synthetic private trip A");
  } finally { context.release(); context.close(); }
});

test("a session change after readiness removes private labels from the hidden DOM too", async () => {
  const context = await startup();
  try {
    await context.entered; context.release(); await settled(context);
    context.window.localStorage.setItem(OWNER_KEY, OTHER);
    context.window.dispatchEvent(new context.window.StorageEvent("storage", { key: OWNER_KEY, oldValue: OWNER, newValue: OTHER }));
    assert.equal(context.window.document.getElementById("offline-scanner").hidden, true);
    assert.doesNotMatch(context.window.document.body.textContent, /Synthetic private trip A|Synthetic private activity A/);
  } finally { context.release(); context.close(); }
});

test("a delayed count for an earlier activity cannot overwrite the selected activity count", async () => {
  const context = await startup({ extraSession: true });
  try {
    await context.entered; context.release(); await settled(context);
    await new Promise(resolve => setTimeout(resolve, 20));
    for (const [id, sessionId] of [["first", SESSION], ["second-a", SECOND_SESSION], ["second-b", SECOND_SESSION]]) {
      context.storage.rows(PENDING_STORE).set(id, { id, ownerUserId: OWNER, groupId: GROUP, sessionId });
    }
    context.holdPendingReads();
    const select = context.window.document.getElementById("session-select");
    select.dispatchEvent(new context.window.Event("change"));
    await waitUntil(() => context.pendingReads.length === 1);
    select.value = SECOND_SESSION; select.dispatchEvent(new context.window.Event("change"));
    await waitUntil(() => context.pendingReads.length === 2);
    context.pendingReads[1]();
    await waitUntil(() => context.window.document.getElementById("pending-count").textContent === "2");
    context.pendingReads[0](); await new Promise(resolve => setTimeout(resolve, 10));
    assert.equal(select.value, SECOND_SESSION);
    assert.equal(context.window.document.getElementById("pending-count").textContent, "2");
  } finally { context.release(); context.close(); }
});

test("a failed old count cannot replace the current activity's successful count", async () => {
  const context = await startup({ extraSession: true });
  try {
    await context.entered; context.release(); await settled(context);
    await new Promise(resolve => setTimeout(resolve, 20));
    context.holdPendingReads();
    const select = context.window.document.getElementById("session-select");
    select.dispatchEvent(new context.window.Event("change"));
    await waitUntil(() => context.pendingReads.length === 1);
    select.value = SECOND_SESSION; select.dispatchEvent(new context.window.Event("change"));
    await waitUntil(() => context.pendingReads.length === 2);
    context.pendingReads[1](); await new Promise(resolve => setTimeout(resolve, 10));
    context.pendingReads[0](new Error("Synthetic previous activity read failure"));
    await new Promise(resolve => setTimeout(resolve, 10));
    assert.equal(context.window.document.getElementById("pending-count").textContent, "0");
    select.dispatchEvent(new context.window.Event("change"));
    await waitUntil(() => context.pendingReads.length === 3);
    context.pendingReads[2](new Error("Synthetic current activity read failure"));
    await waitUntil(() => context.window.document.getElementById("pending-count").textContent === "Unavailable");
  } finally { context.release(); context.close(); }
});
