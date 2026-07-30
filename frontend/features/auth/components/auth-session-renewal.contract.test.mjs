import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const client = readFileSync(
  new URL("../../../lib/api/client.ts", import.meta.url),
  "utf8",
);
const hydrator = readFileSync(
  new URL("./auth-hydrator.tsx", import.meta.url),
  "utf8",
);
const gate = readFileSync(
  new URL("./authenticated-content.tsx", import.meta.url),
  "utf8",
);
const store = readFileSync(
  new URL("../../../stores/auth.store.ts", import.meta.url),
  "utf8",
);
const dashboardLayout = readFileSync(
  new URL("../../../app/(dashboard)/layout.tsx", import.meta.url),
  "utf8",
);
const coordinatorLayout = readFileSync(
  new URL("../../../app/coordinator/layout.tsx", import.meta.url),
  "utf8",
);

test("protected workspaces renew before mounting feature queries", () => {
  assert.match(client, /export function refreshAuthenticatedSession\(\)/);
  assert.match(hydrator, /void renewSession\(\);/);
  assert.match(hydrator, /session\.access_token_expires_at/);
  assert.match(hydrator, /SESSION_REFRESH_SAFETY_WINDOW_MS/);
  assert.match(gate, /if \(!hasHydrated \|\| !isAuthenticated\)/);
  assert.match(dashboardLayout, /<AuthenticatedContent>/);
  assert.match(coordinatorLayout, /<AuthenticatedContent>/);
});

test("only rejected refresh credentials expire the browser session", () => {
  assert.match(
    client,
    /error\.response\?\.status === 401 \|\| error\.response\?\.status === 403/,
  );
  assert.match(client, /revokeServerSession: false/);
  assert.match(hydrator, /SESSION_REFRESH_RETRY_DELAY_MS/);
});

test("expired sessions redirect before bounded cleanup finishes", () => {
  const redirect = store.indexOf("window.location.replace(destination)");
  const cleanupWait = store.indexOf("await cleanup");
  assert.ok(redirect >= 0, "clearSession must navigate to the login page");
  assert.ok(
    cleanupWait > redirect,
    "navigation must begin before slow cache and IndexedDB cleanup completes",
  );
});
