import assert from "node:assert/strict";
import test from "node:test";
import { getOrCreatePublicUploadSessionId } from "./public-upload-session.ts";

function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
}

test("reuses one opaque bootstrap session per upload-link browser tab", () => {
  const storage = memoryStorage();
  let generated = 0;
  const options = {
    storage,
    randomId: () => `fixed-${++generated}-12345678`,
  };

  const first = getOrCreatePublicUploadSessionId("group-token-a", options);
  const second = getOrCreatePublicUploadSessionId("group-token-a", options);
  const otherGroup = getOrCreatePublicUploadSessionId("group-token-b", options);

  assert.equal(first, "bootstrap-fixed-1-12345678");
  assert.equal(second, first);
  assert.equal(otherGroup, "bootstrap-fixed-2-12345678");
});

test("replaces malformed stored values instead of forwarding them", () => {
  const storage = memoryStorage();
  storage.setItem("gct:public-upload-bootstrap:group-token", "bad value");

  assert.equal(
    getOrCreatePublicUploadSessionId("group-token", {
      storage,
      randomId: () => "safe-identifier-12345678",
    }),
    "bootstrap-safe-identifier-12345678",
  );
});

test("still creates a bounded session when storage is unavailable", () => {
  const unavailableStorage = {
    getItem: () => {
      throw new Error("storage disabled");
    },
    setItem: () => {
      throw new Error("storage disabled");
    },
  };

  const options = {
    storage: unavailableStorage,
    randomId: () => "fallback-12345678",
  };
  const first = getOrCreatePublicUploadSessionId("unavailable-group-token", options);
  const second = getOrCreatePublicUploadSessionId("unavailable-group-token", {
    ...options,
    randomId: () => "must-not-replace-12345678",
  });
  assert.equal(first, "bootstrap-fallback-12345678");
  assert.equal(second, first);
});
