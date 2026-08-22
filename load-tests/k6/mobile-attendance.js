import { check, fail, sleep } from "k6";
import { SharedArray } from "k6/data";
import exec from "k6/execution";
import http from "k6/http";
import { Counter, Rate, Trend } from "k6/metrics";

import {
  CANONICAL_ATTENDANCE_LOAD,
  validateAttendanceCountReconciliation,
  validateAttendanceLoadEntries,
} from "./mobile-attendance-load-contract.mjs";
import {
  boundedIntegerSetting,
  validateLoadEnvironment,
} from "./mobile-load-contract.mjs";

const contract = validateLoadEnvironment(__ENV);
const BASE_URL = contract.baseUrl;
const RUN_ID = contract.runId;
const DATA_PATH = __ENV.MOBILE_ATTENDANCE_LOAD_DATA || "./mobile-attendance-load-data.json";
const coordinatorCount = boundedIntegerSetting(
  __ENV.MOBILE_ATTENDANCE_COORDINATORS,
  CANONICAL_ATTENDANCE_LOAD.coordinatorCount,
  CANONICAL_ATTENDANCE_LOAD.coordinatorCount,
  CANONICAL_ATTENDANCE_LOAD.coordinatorCount,
  "MOBILE_ATTENDANCE_COORDINATORS",
);
const scansPerCoordinator = boundedIntegerSetting(
  __ENV.MOBILE_ATTENDANCE_SCANS_PER_COORDINATOR,
  CANONICAL_ATTENDANCE_LOAD.scansPerCoordinator,
  CANONICAL_ATTENDANCE_LOAD.scansPerCoordinator,
  CANONICAL_ATTENDANCE_LOAD.scansPerCoordinator,
  "MOBILE_ATTENDANCE_SCANS_PER_COORDINATOR",
);
const scanIntervalMs = boundedIntegerSetting(
  __ENV.MOBILE_ATTENDANCE_SCAN_INTERVAL_MS,
  3750,
  100,
  60_000,
  "MOBILE_ATTENDANCE_SCAN_INTERVAL_MS",
);
const duplicatesPerCoordinator = boundedIntegerSetting(
  __ENV.MOBILE_ATTENDANCE_DUPLICATES_PER_COORDINATOR,
  CANONICAL_ATTENDANCE_LOAD.duplicatesPerCoordinator,
  CANONICAL_ATTENDANCE_LOAD.duplicatesPerCoordinator,
  CANONICAL_ATTENDANCE_LOAD.duplicatesPerCoordinator,
  "MOBILE_ATTENDANCE_DUPLICATES_PER_COORDINATOR",
);
const expectedDuplicateAttempts = coordinatorCount * duplicatesPerCoordinator;

const coordinators = new SharedArray("mobile-attendance-coordinators", () => (
  validateAttendanceLoadEntries(
    JSON.parse(open(DATA_PATH)),
    coordinatorCount,
    scansPerCoordinator,
    duplicatesPerCoordinator,
  )
));

const acknowledgementLatency = new Trend("mobile_attendance_acknowledgement_latency", true);
const accepted = new Rate("mobile_attendance_accept_success");
const authorizationFailures = new Counter("mobile_attendance_authorization_failures");
const rateLimited = new Counter("mobile_attendance_rate_limited");
const proxyFailures = new Counter("mobile_attendance_proxy_failures");
const contractFailures = new Counter("mobile_attendance_contract_failures");
const unexpectedDuplicateResults = new Counter("mobile_attendance_unexpected_duplicate_results");
const deliberateDuplicateAttempts = new Counter("mobile_attendance_deliberate_duplicate_attempts");
const deliberateDuplicateSuccess = new Rate("mobile_attendance_deliberate_duplicate_success");
const deliberateDuplicateLatency = new Trend(
  "mobile_attendance_deliberate_duplicate_acknowledgement_latency",
  true,
);
const reconciliationFailures = new Counter("mobile_attendance_reconciliation_failures");

export const options = {
  scenarios: {
    attendance_event: {
      executor: "per-vu-iterations",
      vus: coordinatorCount,
      iterations: scansPerCoordinator,
      maxDuration: "60m",
      gracefulStop: "30s",
    },
  },
  setupTimeout: "30s",
  summaryTrendStats: ["avg", "med", "p(90)", "p(95)", "p(99)", "max"],
  systemTags: ["status", "method", "name", "scenario", "expected_response"],
  tags: { test_surface: "mobile_attendance" },
  thresholds: {
    mobile_attendance_accept_success: ["rate==1"],
    mobile_attendance_acknowledgement_latency: ["p(95)<2000", "p(99)<5000"],
    mobile_attendance_authorization_failures: ["count==0"],
    mobile_attendance_rate_limited: ["count==0"],
    mobile_attendance_proxy_failures: ["count==0"],
    mobile_attendance_contract_failures: ["count==0"],
    mobile_attendance_unexpected_duplicate_results: ["count==0"],
    mobile_attendance_deliberate_duplicate_attempts: [`count==${expectedDuplicateAttempts}`],
    mobile_attendance_deliberate_duplicate_success: ["rate==1"],
    mobile_attendance_deliberate_duplicate_acknowledgement_latency: [
      "p(95)<2000",
      "p(99)<5000",
    ],
    mobile_attendance_reconciliation_failures: ["count==0"],
    http_req_failed: ["rate<0.005"],
  },
  userAgent: "PassDetection-k6-authorized-mobile-attendance/1.0",
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

function recordFailure(response) {
  if (response.status === 401 || response.status === 403) authorizationFailures.add(1);
  else if (response.status === 429) rateLimited.add(1);
  else if (response.status === 0 || response.status >= 502) proxyFailures.add(1);
}

function hasExactKeys(value, expectedKeys) {
  const actualKeys = Object.keys(value).sort();
  const sortedExpectedKeys = [...expectedKeys].sort();
  return actualKeys.length === sortedExpectedKeys.length
    && actualKeys.every((key, index) => key === sortedExpectedKeys[index]);
}

function validAttendanceResult(value) {
  return value
    && typeof value === "object"
    && !Array.isArray(value)
    && hasExactKeys(value, ["client_event_id", "status", "server_version", "reason_code"])
    && typeof value.client_event_id === "string"
    && ["accepted", "already_applied", "rejected", "refresh_required"].includes(value.status)
    && (value.server_version === null
      || (Number.isSafeInteger(value.server_version) && value.server_version >= 0))
    && (value.reason_code === null
      || (typeof value.reason_code === "string" && value.reason_code.length <= 100));
}

function fetchCanonicalAttendanceCount(expectedScannedCount, phase) {
  const coordinator = coordinators[0];
  const response = http.get(
    `${BASE_URL}/mobile/coordinator/groups/${coordinator.tripId}/attendance/sessions/${coordinator.sessionId}?limit=1`,
    {
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${coordinator.accessToken}`,
        "X-Load-Test-ID": RUN_ID,
      },
      tags: { endpoint: "mobile_attendance_session", name: `GET attendance ${phase} reconciliation` },
      timeout: "15s",
    },
  );
  recordFailure(response);
  try {
    const summary = validateAttendanceCountReconciliation(
      responseJson(response, 512 * 1024),
      coordinator.sessionId,
      coordinatorCount * scansPerCoordinator,
      expectedScannedCount,
    );
    if (summary.status !== "active") {
      throw new Error("The canonical synthetic attendance activity is not active");
    }
    return summary;
  } catch {
    reconciliationFailures.add(1);
    throw new Error(`Canonical attendance ${phase} reconciliation failed`);
  }
}

function submitAttendanceAction(coordinator, action, clientEventId, requestName) {
  const response = http.post(
    `${BASE_URL}/mobile/coordinator/groups/${coordinator.tripId}/attendance/actions`,
    JSON.stringify({
      actions: [{
        client_event_id: clientEventId,
        scanned_at: new Date().toISOString(),
        session_id: coordinator.sessionId,
        signed_qr: action.signedQr,
        source: "qr",
      }],
    }),
    {
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${coordinator.accessToken}`,
        "Content-Type": "application/json",
        "X-Load-Test-ID": RUN_ID,
      },
      tags: { endpoint: "mobile_attendance_actions", name: requestName },
      timeout: "15s",
    },
  );
  recordFailure(response);
  const payload = responseJson(response, 512 * 1024);
  const result = payload
    && hasExactKeys(payload, ["results"])
    && Array.isArray(payload.results)
    ? payload.results
    : undefined;
  const matching = Array.isArray(result)
    && result.length === 1
    && validAttendanceResult(result[0])
    && result[0].client_event_id === clientEventId
    ? result[0]
    : undefined;
  if (!matching) contractFailures.add(1);
  return { matching, response };
}

export function setup() {
  const liveResponse = http.get(`${BASE_URL}/health/live`, {
    headers: { Accept: "application/json", "X-Load-Test-ID": RUN_ID },
    tags: { endpoint: "liveness", name: "GET staging identity preflight" },
    timeout: "15s",
  });
  const livePayload = responseJson(liveResponse, 256 * 1024);
  if (!livePayload || livePayload.status !== "alive" || livePayload.environment !== "staging") {
    throw new Error("The target did not identify itself as APP_ENV=staging; attendance load was not started");
  }
  const readyResponse = http.get(`${BASE_URL}/health/ready`, {
    headers: { Accept: "application/json", "X-Load-Test-ID": RUN_ID },
    tags: { endpoint: "readiness", name: "GET attendance readiness preflight" },
    timeout: "15s",
  });
  const readyPayload = responseJson(readyResponse, 256 * 1024);
  if (!readyPayload || readyPayload.status !== "ready") {
    throw new Error("Staging readiness preflight failed; attendance load was not started");
  }
  fetchCanonicalAttendanceCount(0, "preflight");
}

export function teardown() {
  fetchCanonicalAttendanceCount(coordinatorCount * scansPerCoordinator, "final");
}

export default function submitSyntheticAttendance() {
  const coordinator = coordinators[exec.vu.idInTest - 1];
  const action = coordinator?.actions[exec.vu.iterationInScenario];
  if (!coordinator || !action) fail("No unique synthetic attendance action was assigned");

  sleep((scanIntervalMs * (0.75 + Math.random() * 0.5)) / 1000);
  const { matching, response } = submitAttendanceAction(
    coordinator,
    action,
    action.clientEventId,
    "POST mobile attendance fresh action",
  );
  acknowledgementLatency.add(response.timings.duration);
  const isAccepted = matching?.status === "accepted";
  if (matching?.status === "already_applied") unexpectedDuplicateResults.add(1);
  else if (matching && !isAccepted) contractFailures.add(1);
  accepted.add(isAccepted);
  check(response, {
    "fresh synthetic attendance action is accepted exactly once": () => isAccepted,
  });

  if (action.duplicateClientEventId !== null) {
    deliberateDuplicateAttempts.add(1);
    const duplicate = submitAttendanceAction(
      coordinator,
      action,
      action.duplicateClientEventId,
      "POST mobile attendance deliberate duplicate",
    );
    deliberateDuplicateLatency.add(duplicate.response.timings.duration);
    const isAlreadyApplied = duplicate.matching?.status === "already_applied"
      && duplicate.matching.reason_code === null;
    if (duplicate.matching && !isAlreadyApplied) contractFailures.add(1);
    deliberateDuplicateSuccess.add(isAlreadyApplied);
    check(duplicate.response, {
      "deliberate duplicate is idempotently acknowledged without recounting": () => isAlreadyApplied,
    });
  }
}
