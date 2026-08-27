import { check, fail, sleep } from "k6";
import crypto from "k6/crypto";
import { SharedArray } from "k6/data";
import exec from "k6/execution";
import http from "k6/http";
import { Counter, Rate, Trend } from "k6/metrics";
import ws from "k6/ws";

import {
  DASHBOARD_LOAD_THRESHOLDS,
  boundedIntegerSetting,
  maximumVus,
  minimumCredentialRemainingSeconds,
  stagesForDashboardProfile,
  validateDashboardCredentialManifest,
  validateDashboardLoadEnvironment,
} from "./dashboard-load-contract.mjs";

const contract = validateDashboardLoadEnvironment(__ENV);
const stages = stagesForDashboardProfile(contract.profile, contract.mode);
const maximumUsers = maximumVus(stages);
const requiredSessionLifetimeSeconds = minimumCredentialRemainingSeconds(stages);
const socketLifetimeSeconds = boundedIntegerSetting(
  __ENV.DASHBOARD_SOCKET_LIFETIME_SECONDS,
  contract.mode === "soak" ? 45 : 20,
  15,
  60,
  "DASHBOARD_SOCKET_LIFETIME_SECONDS",
);
const thinkTimeSeconds = boundedIntegerSetting(
  __ENV.DASHBOARD_THINK_TIME_SECONDS,
  5,
  1,
  15,
  "DASHBOARD_THINK_TIME_SECONDS",
);
const credentials = new SharedArray("dashboard-load-credentials", () => {
  const manifestSource = open(contract.credentialsPath);
  const calculatedManifestSha256 = crypto.sha256(manifestSource, "hex");
  if (calculatedManifestSha256 !== contract.credentialsSha256) {
    throw new Error("The dashboard credential manifest SHA-256 digest does not match");
  }
  let parsed;
  try {
    parsed = JSON.parse(manifestSource);
  } catch {
    throw new Error("The dashboard credential manifest is not valid JSON");
  }
  return validateDashboardCredentialManifest(parsed, {
    minimumRemainingSeconds: requiredSessionLifetimeSeconds,
    requiredCount: maximumUsers,
    runId: contract.runId,
    targetOrigin: contract.stagingOrigin,
  });
});

const ACCESS_COOKIE_NAME = "access_token";
const INVALIDATIONS = new Set([
  "all",
  "announcements",
  "attendance",
  "documents",
  "itinerary",
  "operations",
  "roster",
]);
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const requestSuccess = new Rate("dashboard_request_success");
const statsLatency = new Trend("dashboard_stats_latency", true);
const notificationFeedLatency = new Trend("dashboard_notification_feed_latency", true);
const authorizationFailures = new Counter("dashboard_authorization_failures");
const rateLimited = new Counter("dashboard_rate_limited");
const proxyFailures = new Counter("dashboard_proxy_failures");
const connectionFailures = new Counter("dashboard_connection_failures");
const contractFailures = new Counter("dashboard_contract_failures");
const realtimeConnectionSuccess = new Rate("dashboard_realtime_connection_success");
const realtimeReadyLatency = new Trend("dashboard_realtime_ready_latency", true);
const realtimeProtocolFailures = new Counter("dashboard_realtime_protocol_failures");
const realtimeAuthorizationFailures = new Counter(
  "dashboard_realtime_authorization_failures",
);
const realtimeUnexpectedDisconnects = new Rate(
  "dashboard_realtime_unexpected_disconnects",
);
const realtimeHints = new Counter("dashboard_realtime_hints");

export const options = {
  discardResponseBodies: true,
  scenarios: {
    dashboard_users: {
      executor: "ramping-vus",
      stages,
      gracefulRampDown: "2m",
      gracefulStop: "2m",
    },
  },
  setupTimeout: "30s",
  summaryTrendStats: ["avg", "med", "p(90)", "p(95)", "p(99)", "max"],
  systemTags: [
    "status",
    "method",
    "name",
    "scenario",
    "expected_response",
  ],
  tags: {
    load_mode: contract.mode,
    load_profile: contract.profile,
    run_id: contract.runId,
    test_surface: "dashboard",
  },
  thresholds: DASHBOARD_LOAD_THRESHOLDS,
  userAgent: "PassDetection-k6-authorized-dashboard/1.0",
};

function responseJson(response, maximumBytes) {
  if (
    response.status !== 200
    || typeof response.body !== "string"
    || response.body.length > maximumBytes
    || !(response.headers["Content-Type"] || response.headers["content-type"] || "")
      .toLowerCase().includes("application/json")
  ) {
    return undefined;
  }
  try {
    const parsed = JSON.parse(response.body);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
}

function hasJsonContentType(response) {
  return (response.headers["Content-Type"] || response.headers["content-type"] || "")
    .toLowerCase().includes("application/json");
}

function recordHttpResult(response, latencyMetric, checkName) {
  latencyMetric.add(response.timings.duration);
  if (response.status === 401 || response.status === 403) authorizationFailures.add(1);
  if (response.status === 429) rateLimited.add(1);
  if (response.status === 0) connectionFailures.add(1);
  if (response.status >= 502 && response.status <= 504) proxyFailures.add(1);

  const valid = response.status === 200 && hasJsonContentType(response);
  if (!valid) contractFailures.add(1);
  requestSuccess.add(check(response, {
    [checkName]: () => valid,
  }));
}

function requestHeaders(credential) {
  return {
    Accept: "application/json",
    Cookie: `${ACCESS_COOKIE_NAME}=${credential.sessionCookieValue}`,
    "X-Load-Test-ID": contract.runId,
  };
}

function readDashboard(credential) {
  const headers = requestHeaders(credential);
  const [statsResponse, notificationResponse] = http.batch([
    ["GET", `${contract.baseUrl}/dashboard/stats`, null, {
      headers,
      redirects: 0,
      responseType: "none",
      tags: { endpoint: "dashboard_stats", name: "GET dashboard stats" },
      timeout: "10s",
    }],
    ["GET", `${contract.baseUrl}/notifications/feed?unread_only=false&limit=10`, null, {
      headers,
      redirects: 0,
      responseType: "none",
      tags: {
        endpoint: "dashboard_notification_feed",
        name: "GET dashboard notification feed",
      },
      timeout: "10s",
    }],
  ]);
  recordHttpResult(
    statsResponse,
    statsLatency,
    "dashboard stats returned a bounded JSON response",
  );
  recordHttpResult(
    notificationResponse,
    notificationFeedLatency,
    "notification feed returned a bounded JSON response",
  );
}

function hasExactKeys(value, expectedKeys) {
  const actual = Object.keys(value).sort();
  const expected = [...expectedKeys].sort();
  return actual.length === expected.length
    && actual.every((key, index) => key === expected[index]);
}

function validReadyFrame(frame) {
  return frame
    && typeof frame === "object"
    && !Array.isArray(frame)
    && hasExactKeys(frame, ["type", "heartbeat_seconds", "idle_timeout_seconds"])
    && frame.type === "ready"
    && Number.isSafeInteger(frame.heartbeat_seconds)
    && frame.heartbeat_seconds >= 5
    && frame.heartbeat_seconds <= 60
    && Number.isSafeInteger(frame.idle_timeout_seconds)
    && frame.idle_timeout_seconds >= 15
    && frame.idle_timeout_seconds <= 180
    && frame.idle_timeout_seconds > frame.heartbeat_seconds * 2;
}

function validSyncHintFrame(frame) {
  return frame
    && typeof frame === "object"
    && !Array.isArray(frame)
    && hasExactKeys(frame, ["type", "trip_id", "cursor", "invalidation"])
    && frame.type === "sync_hint"
    && typeof frame.trip_id === "string"
    && UUID_PATTERN.test(frame.trip_id)
    && Number.isSafeInteger(frame.cursor)
    && frame.cursor >= 1
    && typeof frame.invalidation === "string"
    && INVALIDATIONS.has(frame.invalidation);
}

function exerciseRealtime(credential) {
  const startedAt = Date.now();
  const plannedLifetimeMs = Math.round(
    socketLifetimeSeconds * 1000 * (0.9 + Math.random() * 0.2),
  );
  let ready = false;
  let plannedClose = false;
  let socketError = false;
  let closeCode = 0;

  const response = ws.connect(contract.websocketUrl, {
    headers: {
      Cookie: `${ACCESS_COOKIE_NAME}=${credential.sessionCookieValue}`,
      Origin: contract.stagingOrigin,
      "X-Load-Test-ID": contract.runId,
    },
    tags: {
      endpoint: "dashboard_realtime",
      name: "CONNECT dashboard realtime",
    },
  }, (socket) => {
    socket.setTimeout(() => {
      plannedClose = true;
      socket.close(1000);
    }, plannedLifetimeMs);

    socket.on("message", (raw) => {
      let frame;
      try {
        if (typeof raw !== "string" || raw.length > 1024) {
          throw new Error("invalid realtime frame size");
        }
        frame = JSON.parse(raw);
      } catch {
        realtimeProtocolFailures.add(1);
        return;
      }

      if (!ready && validReadyFrame(frame)) {
        ready = true;
        realtimeReadyLatency.add(Date.now() - startedAt);
      } else if (
        ready
        && frame
        && typeof frame === "object"
        && !Array.isArray(frame)
        && hasExactKeys(frame, ["type"])
        && frame.type === "heartbeat"
      ) {
        socket.send(JSON.stringify({ type: "heartbeat_ack" }));
      } else if (ready && validSyncHintFrame(frame)) {
        realtimeHints.add(1);
      } else {
        realtimeProtocolFailures.add(1);
      }
    });
    socket.on("error", () => {
      if (!plannedClose) socketError = true;
    });
    socket.on("close", (code) => {
      if (Number.isSafeInteger(code)) closeCode = code;
    });
  });

  const upgraded = check(response, {
    "dashboard realtime upgraded with HTTP 101": (value) => value && value.status === 101,
  });
  if (response && (response.status === 401 || response.status === 403)) {
    realtimeAuthorizationFailures.add(1);
  }
  if (closeCode === 4401 || closeCode === 4403) realtimeAuthorizationFailures.add(1);
  if (response && response.status === 429) rateLimited.add(1);
  if (!response || response.status === 0) connectionFailures.add(1);
  if (response && response.status >= 502 && response.status <= 504) proxyFailures.add(1);

  const connectedAndReady = Boolean(upgraded && ready);
  realtimeConnectionSuccess.add(connectedAndReady);
  realtimeUnexpectedDisconnects.add(
    !plannedClose || socketError || !connectedAndReady || (closeCode !== 0 && closeCode !== 1000),
  );
}

export function setup() {
  const liveResponse = http.get(`${contract.baseUrl}/health/live`, {
    headers: { Accept: "application/json", "X-Load-Test-ID": contract.runId },
    redirects: 0,
    responseType: "text",
    tags: { endpoint: "liveness", name: "GET staging identity preflight" },
    timeout: "15s",
  });
  const livePayload = responseJson(liveResponse, 256 * 1024);
  if (
    !livePayload
    || livePayload.status !== "alive"
    || livePayload.environment !== "staging"
    || livePayload.revision !== contract.expectedRevision
  ) {
    throw new Error(
      "The target did not identify as the approved APP_ENV=staging revision; no session was sent",
    );
  }

  const readyResponse = http.get(`${contract.baseUrl}/health/ready`, {
    headers: { Accept: "application/json", "X-Load-Test-ID": contract.runId },
    redirects: 0,
    responseType: "text",
    tags: { endpoint: "readiness", name: "GET dashboard readiness preflight" },
    timeout: "15s",
  });
  const readyPayload = responseJson(readyResponse, 256 * 1024);
  if (
    !readyPayload
    || readyPayload.status !== "ready"
    || readyPayload.revision !== contract.expectedRevision
    || !readyPayload.checks
    || readyPayload.checks.database !== "ok"
    || readyPayload.checks.mobile_realtime !== "ok"
  ) {
    throw new Error("The approved staging dashboard was not ready; no session was sent");
  }
  return Object.freeze({ stagingIdentityVerified: true });
}

export default function dashboardUser(preflight) {
  if (!preflight || preflight.stagingIdentityVerified !== true) {
    fail("The staging identity preflight did not complete");
  }
  const credential = credentials[exec.vu.idInTest - 1];
  if (!credential) fail("No unique dashboard session was assigned to this virtual user");

  sleep(Math.random() * 2);
  readDashboard(credential);
  exerciseRealtime(credential);
  sleep(thinkTimeSeconds * (0.5 + Math.random()));
}
