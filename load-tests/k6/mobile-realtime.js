import { check, fail, sleep } from "k6";
import { SharedArray } from "k6/data";
import exec from "k6/execution";
import http from "k6/http";
import ws from "k6/ws";
import { Counter, Rate, Trend } from "k6/metrics";

import {
  boundedIntegerSetting,
  maximumVus,
  stagesForProfile,
  validateCredentialEntries,
  validateLoadEnvironment,
} from "./mobile-load-contract.mjs";

const contract = validateLoadEnvironment(__ENV);
const BASE_URL = contract.baseUrl;
const DATA_PATH = __ENV.MOBILE_LOAD_DATA || "./mobile-load-data.json";
const PROFILE = contract.profile;
const RUN_ID = contract.runId;
const stages = stagesForProfile(PROFILE);
const maximumClients = maximumVus(stages);
const socketLifetimeSeconds = boundedIntegerSetting(
  __ENV.MOBILE_SOCKET_LIFETIME_SECONDS,
  PROFILE === "smoke" ? 45 : 900,
  30,
  3600,
  "MOBILE_SOCKET_LIFETIME_SECONDS",
);

const credentials = new SharedArray("mobile-realtime-credentials", () => (
  validateCredentialEntries(JSON.parse(open(DATA_PATH)), maximumClients)
));

const socketUrl = `${BASE_URL.replace(/^https:/i, "wss:")}/mobile/realtime`;
const connectionSuccess = new Rate("mobile_realtime_connection_success");
const readyLatency = new Trend("mobile_realtime_ready_latency", true);
const sessionDuration = new Trend("mobile_realtime_session_duration", true);
const hintCount = new Counter("mobile_realtime_hints");
const invalidFrameCount = new Counter("mobile_realtime_invalid_frames");
const scopeViolations = new Counter("mobile_realtime_scope_violations");
const cursorRegressions = new Counter("mobile_realtime_cursor_regressions");
const unexpectedDisconnects = new Rate("mobile_realtime_unexpected_disconnects");
const INVALIDATIONS = [
  "all",
  "announcements",
  "attendance",
  "documents",
  "itinerary",
  "operations",
  "roster",
];

export const options = {
  scenarios: {
    foreground_realtime: {
      executor: "ramping-vus",
      stages,
      gracefulRampDown: "30s",
      gracefulStop: "30s",
    },
  },
  setupTimeout: "30s",
  summaryTrendStats: ["avg", "med", "p(90)", "p(95)", "p(99)", "max"],
  systemTags: ["status", "name", "scenario", "expected_response"],
  tags: { load_profile: PROFILE, test_surface: "mobile_realtime" },
  thresholds: {
    mobile_realtime_connection_success: ["rate>0.99"],
    mobile_realtime_ready_latency: ["p(95)<2000", "p(99)<5000"],
    mobile_realtime_invalid_frames: ["count==0"],
    mobile_realtime_scope_violations: ["count==0"],
    mobile_realtime_cursor_regressions: ["count==0"],
    mobile_realtime_unexpected_disconnects: ["rate<0.01"],
    ws_connecting: ["p(95)<2000", "p(99)<5000"],
  },
  userAgent: "PassDetection-k6-authorized-mobile-realtime/2.0",
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

export function setup() {
  const liveResponse = http.get(`${BASE_URL}/health/live`, {
    headers: { Accept: "application/json", "X-Load-Test-ID": RUN_ID },
    tags: { endpoint: "liveness", name: "GET staging identity preflight" },
    timeout: "15s",
  });
  const livePayload = responseJson(liveResponse, 256 * 1024);
  if (!livePayload || livePayload.status !== "alive" || livePayload.environment !== "staging") {
    throw new Error("The target did not identify itself as APP_ENV=staging; the load test was not started");
  }
  const response = http.get(`${BASE_URL}/health/ready`, {
    headers: { Accept: "application/json", "X-Load-Test-ID": RUN_ID },
    tags: { endpoint: "readiness", name: "GET realtime readiness preflight" },
    timeout: "15s",
  });
  const payload = responseJson(response, 256 * 1024);
  if (
    !payload
    || payload.status !== "ready"
    || !payload.checks
    || payload.checks.mobile_realtime !== "ok"
  ) {
    throw new Error("Staging realtime readiness preflight failed; the load test was not started");
  }
}

function hasExactKeys(value, expectedKeys) {
  const actualKeys = Object.keys(value).sort();
  const sortedExpectedKeys = [...expectedKeys].sort();
  return actualKeys.length === sortedExpectedKeys.length
    && actualKeys.every((key, index) => key === sortedExpectedKeys[index]);
}

export default function realtimeClient() {
  const credential = credentials[exec.vu.idInTest - 1];
  if (!credential) fail("No unique credential was assigned to this virtual user");

  sleep(Math.random() * 2);
  const startedAt = Date.now();
  const plannedLifetimeMs = Math.round(
    socketLifetimeSeconds * 1000 * (0.9 + Math.random() * 0.2),
  );
  let ready = false;
  let plannedClose = false;
  let socketError = false;
  const lastHintCursorByTrip = {};
  const response = ws.connect(socketUrl, {
    headers: {
      Authorization: `Bearer ${credential.accessToken}`,
      "X-Load-Test-ID": RUN_ID,
    },
    tags: { endpoint: "mobile_realtime", name: "CONNECT mobile realtime" },
  }, (socket) => {
    socket.setTimeout(() => {
      plannedClose = true;
      socket.close(1000);
    }, plannedLifetimeMs);

    socket.on("message", (raw) => {
      let frame;
      try {
        if (typeof raw !== "string" || raw.length > 1024) throw new Error("invalid frame size");
        frame = JSON.parse(raw);
      } catch {
        invalidFrameCount.add(1);
        return;
      }
      if (
        frame
        && typeof frame === "object"
        && !Array.isArray(frame)
        && frame.type === "ready"
        && !ready
        && hasExactKeys(frame, ["type", "heartbeat_seconds", "idle_timeout_seconds"])
        && Number.isSafeInteger(frame.heartbeat_seconds)
        && Number.isSafeInteger(frame.idle_timeout_seconds)
        && frame.heartbeat_seconds > 0
        && frame.idle_timeout_seconds > frame.heartbeat_seconds
      ) {
        ready = true;
        readyLatency.add(Date.now() - startedAt);
      } else if (
        frame
        && typeof frame === "object"
        && !Array.isArray(frame)
        && frame.type === "heartbeat"
        && ready
        && hasExactKeys(frame, ["type"])
      ) {
        socket.send(JSON.stringify({ type: "heartbeat_ack" }));
      } else if (
        frame
        && typeof frame === "object"
        && !Array.isArray(frame)
        && frame.type === "sync_hint"
        && ready
        && hasExactKeys(frame, ["type", "trip_id", "cursor", "invalidation"])
        && INVALIDATIONS.includes(frame.invalidation)
      ) {
        const hintedTripId = typeof frame.trip_id === "string" ? frame.trip_id.toLowerCase() : "";
        if (!credential.tripIds.includes(hintedTripId)) {
          scopeViolations.add(1);
        } else if (
          !Number.isSafeInteger(frame.cursor)
          || frame.cursor < (lastHintCursorByTrip[hintedTripId] || -1)
        ) {
          cursorRegressions.add(1);
        } else {
          lastHintCursorByTrip[hintedTripId] = frame.cursor;
          hintCount.add(1);
        }
      } else {
        invalidFrameCount.add(1);
      }
    });
    socket.on("error", () => {
      if (!plannedClose) socketError = true;
    });
  });

  const duration = Date.now() - startedAt;
  sessionDuration.add(duration);
  const upgraded = check(response, {
    "realtime upgraded with HTTP 101": (value) => value && value.status === 101,
  });
  const connectedAndReady = Boolean(upgraded && ready);
  connectionSuccess.add(connectedAndReady);
  unexpectedDisconnects.add(!plannedClose || socketError || !connectedAndReady);
  sleep(1 + Math.random() * 4);
}
