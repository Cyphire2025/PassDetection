import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  DASHBOARD_LOAD_THRESHOLDS,
  maximumVus,
  minimumCredentialRemainingSeconds,
  stagesForDashboardProfile,
  totalStageDurationSeconds,
  validateDashboardCredentialManifest,
  validateDashboardLoadEnvironment,
} from "./dashboard-load-contract.mjs";

const NOW_MS = Date.parse("2030-01-02T03:04:05.000Z");
const RUN_ID = "dash-load-20300102-a";
const STAGING_ORIGIN = "https://staging.passdetection.example";
const COOKIE_VALUE = "session-cookie-material-that-is-never-printed";

function baseEnvironment(overrides = {}) {
  return {
    DASHBOARD_LOAD_APPROVED: "true",
    DASHBOARD_LOAD_TARGET_ENVIRONMENT: "staging",
    DASHBOARD_LOAD_EXPECTED_ORIGIN: STAGING_ORIGIN,
    DASHBOARD_LOAD_PRODUCTION_ORIGIN: "https://app.passdetection.example",
    DASHBOARD_BASE_URL: `${STAGING_ORIGIN}/api/v1`,
    DASHBOARD_LOAD_RUN_ID: RUN_ID,
    DASHBOARD_LOAD_APPROVAL_REFERENCE: "change-20300102-17",
    DASHBOARD_LOAD_EXPECTED_REVISION: "abcdef1234567",
    DASHBOARD_LOAD_PROFILE: "200",
    DASHBOARD_LOAD_MODE: "soak",
    DASHBOARD_LOAD_REPOSITORY_ROOT: "C:\\workspace\\PassDetection",
    DASHBOARD_LOAD_CREDENTIALS_PATH: `C:\\load-secrets\\dashboard-credentials.${RUN_ID}.json`,
    DASHBOARD_LOAD_CREDENTIALS_SHA256: "a".repeat(64),
    ...overrides,
  };
}

function session(index, overrides = {}) {
  return {
    principal_ref: `load-vu-${String(index + 1).padStart(3, "0")}`,
    session_cookie_value: `${COOKIE_VALUE}-${String(index + 1).padStart(3, "0")}`,
    issued_at: new Date(NOW_MS).toISOString(),
    expires_at: new Date(NOW_MS + 30 * 60 * 1000).toISOString(),
    ...overrides,
  };
}

function manifest(count, overrides = {}) {
  return {
    schema_version: 1,
    run_id: RUN_ID,
    target_origin: STAGING_ORIGIN,
    generated_at: new Date(NOW_MS).toISOString(),
    sessions: Array.from({ length: count }, (_, index) => session(index)),
    ...overrides,
  };
}

test("load and soak profiles model exactly 100 or 200 concurrent dashboard users", () => {
  for (const mode of ["load", "soak"]) {
    for (const profile of ["100", "200"]) {
      const stages = stagesForDashboardProfile(profile, mode);
      assert.equal(maximumVus(stages), Number(profile));
      assert.equal(stages.at(-1)?.target, 0);
      assert.ok(totalStageDurationSeconds(stages) > 0);
    }
  }
  assert.ok(
    totalStageDurationSeconds(stagesForDashboardProfile("200", "soak"))
      > totalStageDurationSeconds(stagesForDashboardProfile("200", "load")),
  );
  assert.throws(
    () => stagesForDashboardProfile("201", "soak"),
    /must be 100 or 200/,
  );
});

test("the soak profile remains inside a freshly minted 30-minute access session", () => {
  const stages = stagesForDashboardProfile("200", "soak");
  assert.equal(totalStageDurationSeconds(stages), 26 * 60);
  assert.equal(minimumCredentialRemainingSeconds(stages), 28 * 60);
  assert.ok(minimumCredentialRemainingSeconds(stages) < 30 * 60);
});

test("environment contract binds approval, staging origin, revision, and external manifest", () => {
  const contract = validateDashboardLoadEnvironment(baseEnvironment());
  assert.equal(contract.baseUrl, `${STAGING_ORIGIN}/api/v1`);
  assert.equal(contract.profile, "200");
  assert.equal(contract.mode, "soak");
  assert.equal(
    contract.websocketUrl,
    "wss://staging.passdetection.example/api/v1/dashboard/realtime",
  );
  assert.equal(
    contract.credentialsPath,
    `c:/load-secrets/dashboard-credentials.${RUN_ID}.json`,
  );
});

test("environment contract fails closed for production, HTTP, or missing approval", () => {
  assert.throws(
    () => validateDashboardLoadEnvironment(baseEnvironment({ DASHBOARD_LOAD_APPROVED: "false" })),
    /authorized/,
  );
  assert.throws(
    () => validateDashboardLoadEnvironment(baseEnvironment({
      DASHBOARD_LOAD_TARGET_ENVIRONMENT: "production",
    })),
    /exactly staging/,
  );
  assert.throws(
    () => validateDashboardLoadEnvironment(baseEnvironment({
      DASHBOARD_LOAD_EXPECTED_ORIGIN: "https://app.passdetection.example",
    })),
    /must be different/,
  );
  assert.throws(
    () => validateDashboardLoadEnvironment(baseEnvironment({
      DASHBOARD_LOAD_EXPECTED_ORIGIN: "http://staging.passdetection.example",
    })),
    /HTTPS origin/,
  );
  assert.throws(
    () => validateDashboardLoadEnvironment(baseEnvironment({
      DASHBOARD_LOAD_EXPECTED_ORIGIN: "https://127.0.0.1",
      DASHBOARD_BASE_URL: "https://127.0.0.1/api/v1",
    })),
    /fully qualified DNS hostname/,
  );
  assert.throws(
    () => validateDashboardLoadEnvironment(baseEnvironment({
      DASHBOARD_LOAD_EXPECTED_REVISION: "unknown",
    })),
    /deployed staging revision/,
  );
  assert.throws(
    () => validateDashboardLoadEnvironment(baseEnvironment({
      DASHBOARD_LOAD_CREDENTIALS_SHA256: "a".repeat(63),
    })),
    /64-character SHA-256/,
  );
});

test("credential path must be run-specific, absolute, and outside the repository", () => {
  assert.throws(
    () => validateDashboardLoadEnvironment(baseEnvironment({
      DASHBOARD_LOAD_CREDENTIALS_PATH:
        `C:\\workspace\\PassDetection\\dashboard-credentials.${RUN_ID}.json`,
    })),
    /outside the repository/,
  );
  assert.throws(
    () => validateDashboardLoadEnvironment(baseEnvironment({
      DASHBOARD_LOAD_REPOSITORY_ROOT: "C:\\WORKSPACE\\PASSDETECTION",
      DASHBOARD_LOAD_CREDENTIALS_PATH:
        `c:\\workspace\\passdetection\\dashboard-credentials.${RUN_ID}.json`,
    })),
    /outside the repository/,
  );
  assert.throws(
    () => validateDashboardLoadEnvironment(baseEnvironment({
      DASHBOARD_LOAD_CREDENTIALS_PATH: `dashboard-credentials.${RUN_ID}.json`,
    })),
    /absolute local path/,
  );
  assert.throws(
    () => validateDashboardLoadEnvironment(baseEnvironment({
      DASHBOARD_LOAD_CREDENTIALS_PATH: "C:\\load-secrets\\dashboard-credentials.other.json",
    })),
    /must end with/,
  );
});

test("manifest accepts exactly one fresh, isolated, short-lived cookie per VU", () => {
  const sessions = validateDashboardCredentialManifest(manifest(200), {
    minimumRemainingSeconds: 28 * 60,
    requiredCount: 200,
    runId: RUN_ID,
    targetOrigin: STAGING_ORIGIN,
    nowMs: NOW_MS,
  });
  assert.equal(sessions.length, 200);
  assert.equal(new Set(sessions.map((entry) => entry.principalRef)).size, 200);
  assert.equal(new Set(sessions.map((entry) => entry.sessionCookieValue)).size, 200);
  assert.ok(Object.isFrozen(sessions));
});

test("manifest rejects extra PII/password fields and unsafe account references", () => {
  const withEmail = manifest(1);
  withEmail.sessions[0] = { ...withEmail.sessions[0], email: "person@example.test" };
  assert.throws(
    () => validateDashboardCredentialManifest(withEmail, {
      minimumRemainingSeconds: 60,
      requiredCount: 1,
      runId: RUN_ID,
      targetOrigin: STAGING_ORIGIN,
      nowMs: NOW_MS,
    }),
    /unexpected or missing fields/,
  );

  const namedPrincipal = manifest(1);
  namedPrincipal.sessions[0] = {
    ...namedPrincipal.sessions[0],
    principal_ref: "alice@example.test",
  };
  assert.throws(
    () => validateDashboardCredentialManifest(namedPrincipal, {
      minimumRemainingSeconds: 60,
      requiredCount: 1,
      runId: RUN_ID,
      targetOrigin: STAGING_ORIGIN,
      nowMs: NOW_MS,
    }),
    /synthetic principal reference/,
  );
});

test("manifest rejects duplicates, stale sessions, long sessions, and count drift without leaks", () => {
  const duplicate = manifest(2);
  duplicate.sessions[1] = {
    ...duplicate.sessions[1],
    session_cookie_value: duplicate.sessions[0].session_cookie_value,
  };
  let duplicateError;
  try {
    validateDashboardCredentialManifest(duplicate, {
      minimumRemainingSeconds: 60,
      requiredCount: 2,
      runId: RUN_ID,
      targetOrigin: STAGING_ORIGIN,
      nowMs: NOW_MS,
    });
  } catch (error) {
    duplicateError = error;
  }
  assert.match(String(duplicateError), /isolated session/);
  assert.doesNotMatch(String(duplicateError), new RegExp(COOKIE_VALUE));

  assert.throws(
    () => validateDashboardCredentialManifest(manifest(1), {
      minimumRemainingSeconds: 60,
      requiredCount: 2,
      runId: RUN_ID,
      targetOrigin: STAGING_ORIGIN,
      nowMs: NOW_MS,
    }),
    /exactly 2/,
  );

  const stale = manifest(1, {
    generated_at: new Date(NOW_MS - 11 * 60 * 1000).toISOString(),
  });
  assert.throws(
    () => validateDashboardCredentialManifest(stale, {
      minimumRemainingSeconds: 60,
      requiredCount: 1,
      runId: RUN_ID,
      targetOrigin: STAGING_ORIGIN,
      nowMs: NOW_MS,
    }),
    /within ten minutes/,
  );

  const tooLong = manifest(1);
  tooLong.sessions[0] = {
    ...tooLong.sessions[0],
    expires_at: new Date(NOW_MS + 46 * 60 * 1000).toISOString(),
  };
  assert.throws(
    () => validateDashboardCredentialManifest(tooLong, {
      minimumRemainingSeconds: 60,
      requiredCount: 1,
      runId: RUN_ID,
      targetOrigin: STAGING_ORIGIN,
      nowMs: NOW_MS,
    }),
    /short-lived run session/,
  );

  const insufficientLifetime = manifest(1);
  insufficientLifetime.sessions[0] = {
    ...insufficientLifetime.sessions[0],
    expires_at: new Date(NOW_MS + 20 * 60 * 1000).toISOString(),
  };
  assert.throws(
    () => validateDashboardCredentialManifest(insufficientLifetime, {
      minimumRemainingSeconds: 28 * 60,
      requiredCount: 1,
      runId: RUN_ID,
      targetOrigin: STAGING_ORIGIN,
      nowMs: NOW_MS,
    }),
    /expires before the run/,
  );
});

test("enterprise thresholds cover latency, auth, rate limit, proxy, connection, and drops", () => {
  assert.deepEqual(DASHBOARD_LOAD_THRESHOLDS.dashboard_stats_latency, [
    "p(95)<750",
    "p(99)<1500",
  ]);
  assert.deepEqual(DASHBOARD_LOAD_THRESHOLDS.dashboard_notification_feed_latency, [
    "p(95)<500",
    "p(99)<1000",
  ]);
  for (const metric of [
    "dashboard_authorization_failures",
    "dashboard_rate_limited",
    "dashboard_proxy_failures",
    "dashboard_connection_failures",
    "dashboard_realtime_authorization_failures",
    "dropped_iterations",
  ]) {
    assert.deepEqual(DASHBOARD_LOAD_THRESHOLDS[metric], ["count==0"]);
  }
  assert.deepEqual(DASHBOARD_LOAD_THRESHOLDS.http_req_failed, ["rate<0.005"]);
  assert.deepEqual(DASHBOARD_LOAD_THRESHOLDS.ws_connecting, [
    "p(95)<1500",
    "p(99)<3000",
  ]);
});

test("harness is cookie-only, read-only, bounded, and discards dashboard response bodies", () => {
  const source = readFileSync(new URL("./dashboard-load.js", import.meta.url), "utf8");
  assert.match(source, /discardResponseBodies:\s*true/);
  assert.match(source, /responseType:\s*"none"/);
  assert.match(source, /Cookie:\s*`\$\{ACCESS_COOKIE_NAME\}=\$\{credential\.sessionCookieValue\}`/);
  assert.match(source, /Origin:\s*contract\.stagingOrigin/);
  assert.match(source, /\/dashboard\/stats/);
  assert.match(source, /\/notifications\/feed\?unread_only=false&limit=10/);
  assert.doesNotMatch(source, /\bAuthorization\s*:/);
  assert.doesNotMatch(source, /http\.(?:post|put|patch|del|delete)\s*\(/);
  assert.doesNotMatch(source, /console\.(?:log|debug|info|warn|error)\s*\(/);
  assert.match(source, /environment !== "staging"/);
  assert.match(source, /revision !== contract\.expectedRevision/);
});
