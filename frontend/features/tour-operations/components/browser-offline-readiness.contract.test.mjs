import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (relativePath) => readFileSync(new URL(relativePath, import.meta.url), "utf8");

const scanner = read("./coordinator-group-scanner.tsx");
const readinessHook = read("../hooks/use-browser-offline-readiness.ts");
const authorization = read("../services/browser-offline-authorization.ts");
const readiness = read("../services/browser-offline-readiness.ts");

test("readiness and QR capture share the same signed trusted-time activity gate", () => {
  assert.match(
    authorization,
    /authorizeBrowserOfflineScan[\s\S]*?requireAuthorizationWindow\([\s\S]*?sha256Hex\(qrPayload\)/,
  );
  assert.match(
    authorization,
    /checkBrowserOfflineReadiness[\s\S]*?requireAuthorizationWindow\(/,
  );
  assert.match(
    authorization,
    /requireAuthorizationWindow[\s\S]*?resolveTrustedTime[\s\S]*?record\.runtimeExpiresAt[\s\S]*?ACTIVITY_EARLY_SKEW_MS/,
  );
});

test("offline reload and lifecycle checks use cached signed readiness", () => {
  assert.match(readiness, /if \(refreshOnline\)[\s\S]*?dependencies\.refresh/);
  assert.match(readiness, /dependencies\.check\(\{ groupId, sessionId \}\)/);
  assert.match(readiness, /transient network failure must not discard an otherwise valid cached/);
  assert.match(readinessHook, /void evaluate\(isOnline && refreshWhenOnline\)/);
  assert.match(readinessHook, /document\.addEventListener\("visibilitychange", handleVisibility\)/);
  assert.match(readinessHook, /window\.addEventListener\("pageshow", handleVisibility\)/);
  assert.match(readinessHook, /BROWSER_OFFLINE_READINESS_RECHECK_MS/);
});

test("camera capture remains available online and fails closed offline until ready", () => {
  assert.match(readiness, /return isOnline \|\| readiness\.status === "ready"/);
  assert.match(scanner, /useContinuousQrScanner\(\{ canAutoResume: canAutoResumeScanner \}\)/);
  assert.match(scanner, /captureAllowedRef\.current = canCapture/);
  assert.match(scanner, /if \(!canCapture\) \{[\s\S]*?autoStartedRef\.current = false;[\s\S]*?stopScanner\(\)/);
  assert.match(scanner, /\|\| !canCapture[\s\S]*?autoStartedRef\.current/);
  assert.match(scanner, /if \(!canCapture \|\| isSessionCompleted \|\| devices\.length < 2\) return/);
  assert.match(scanner, /disabled=\{!canCapture\}[\s\S]*?Retry camera/);
});
