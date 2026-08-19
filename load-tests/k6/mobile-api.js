import { check, fail, sleep } from "k6";
import { SharedArray } from "k6/data";
import exec from "k6/execution";
import http from "k6/http";
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
const clientCount = maximumVus(stages);
const syncIntervalSeconds = boundedIntegerSetting(
  __ENV.MOBILE_SYNC_INTERVAL_SECONDS,
  30,
  5,
  300,
  "MOBILE_SYNC_INTERVAL_SECONDS",
);
const maximumPagesPerCycle = boundedIntegerSetting(
  __ENV.MOBILE_SYNC_MAX_PAGES_PER_CYCLE,
  20,
  1,
  20,
  "MOBILE_SYNC_MAX_PAGES_PER_CYCLE",
);
const manifestEveryCycles = boundedIntegerSetting(
  __ENV.MOBILE_MANIFEST_EVERY_CYCLES,
  20,
  1,
  120,
  "MOBILE_MANIFEST_EVERY_CYCLES",
);

const credentials = new SharedArray("mobile-api-credentials", () => (
  validateCredentialEntries(JSON.parse(open(DATA_PATH)), clientCount)
));

const syncLatency = new Trend("mobile_sync_changes_latency", true);
const manifestLatency = new Trend("mobile_manifest_latency", true);
const requestSuccess = new Rate("mobile_api_request_success");
const authorizationFailures = new Counter("mobile_api_authorization_failures");
const rateLimited = new Counter("mobile_api_rate_limited");
const proxyFailures = new Counter("mobile_api_proxy_failures");
const contractFailures = new Counter("mobile_api_contract_failures");
const cursorRegressions = new Counter("mobile_api_cursor_regressions");
const scopeViolations = new Counter("mobile_api_scope_violations");
const unconvergedCycles = new Counter("mobile_api_unconverged_cycles");

export const options = {
  scenarios: {
    stateful_cursor_reconciliation: {
      executor: "ramping-vus",
      stages,
      gracefulRampDown: "30s",
      gracefulStop: "30s",
    },
  },
  setupTimeout: "30s",
  summaryTrendStats: ["avg", "med", "p(90)", "p(95)", "p(99)", "max"],
  systemTags: ["status", "method", "name", "scenario", "expected_response"],
  tags: { load_profile: PROFILE, test_surface: "mobile_api" },
  thresholds: {
    mobile_api_request_success: ["rate>0.99"],
    mobile_sync_changes_latency: ["p(95)<2000", "p(99)<5000"],
    mobile_manifest_latency: ["p(95)<2000", "p(99)<5000"],
    mobile_api_authorization_failures: ["count==0"],
    mobile_api_rate_limited: ["count==0"],
    mobile_api_proxy_failures: ["count==0"],
    mobile_api_contract_failures: ["count==0"],
    mobile_api_cursor_regressions: ["count==0"],
    mobile_api_scope_violations: ["count==0"],
    mobile_api_unconverged_cycles: ["count==0"],
    http_req_failed: ["rate<0.01"],
  },
  userAgent: "PassDetection-k6-authorized-mobile-api/2.0",
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

function validateSyncPage(payload, requestedCursor, expectedTripId) {
  if (
    !payload
    || !Array.isArray(payload.changes)
    || payload.changes.length > 500
    || !Number.isSafeInteger(payload.next_cursor)
    || typeof payload.has_more !== "boolean"
  ) {
    contractFailures.add(1);
    return undefined;
  }
  if (payload.next_cursor < requestedCursor) {
    cursorRegressions.add(1);
    return undefined;
  }
  if (payload.has_more && payload.changes.length === 0) {
    contractFailures.add(1);
    return undefined;
  }

  let previousSequence = requestedCursor;
  for (const change of payload.changes) {
    if (
      !change
      || typeof change !== "object"
      || !Number.isSafeInteger(change.sequence)
      || change.sequence <= previousSequence
      || change.sequence > payload.next_cursor
      || typeof change.entity_type !== "string"
      || !["upsert", "delete", "revoke"].includes(change.operation)
      || !Number.isSafeInteger(change.version)
      || change.version < 0
    ) {
      cursorRegressions.add(1);
      return undefined;
    }
    if (typeof change.group_id !== "string" || change.group_id.toLowerCase() !== expectedTripId) {
      scopeViolations.add(1);
      return undefined;
    }
    previousSequence = change.sequence;
  }
  if (payload.has_more && payload.next_cursor !== previousSequence) {
    cursorRegressions.add(1);
    return undefined;
  }
  return { hasMore: payload.has_more, nextCursor: payload.next_cursor };
}

function getSyncPage(credential, cursor) {
  const response = http.get(
    `${BASE_URL}/mobile/sync/changes?trip_id=${credential.tripId}&cursor=${cursor}&limit=500`,
    {
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${credential.accessToken}`,
        "X-Load-Test-ID": RUN_ID,
      },
      tags: { endpoint: "mobile_sync_changes", name: "GET mobile sync changes" },
      timeout: "15s",
    },
  );
  syncLatency.add(response.timings.duration);
  recordFailure(response);
  const page = validateSyncPage(responseJson(response, 5 * 1024 * 1024), cursor, credential.tripId);
  requestSuccess.add(check(response, {
    "sync response satisfies the bounded cursor contract": () => page !== undefined,
  }));
  return page;
}

function getManifest(credential, cursor) {
  const response = http.get(`${BASE_URL}/mobile/trips/${credential.tripId}/manifest`, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${credential.accessToken}`,
      "X-Load-Test-ID": RUN_ID,
    },
    tags: { endpoint: "mobile_manifest", name: "GET mobile manifest" },
    timeout: "15s",
  });
  manifestLatency.add(response.timings.duration);
  recordFailure(response);
  const payload = responseJson(response, 1024 * 1024);
  const valid = Boolean(
    payload
    && payload.trip
    && typeof payload.trip.id === "string"
    && payload.trip.id.toLowerCase() === credential.tripId
    && Number.isSafeInteger(payload.sync_cursor)
    && payload.sync_cursor >= cursor
    && payload.resources
    && typeof payload.resources.sync_changes === "string",
  );
  if (!valid) contractFailures.add(1);
  requestSuccess.add(check(response, {
    "manifest response satisfies the trip and cursor contract": () => valid,
  }));
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
    tags: { endpoint: "readiness", name: "GET readiness preflight" },
    timeout: "15s",
  });
  const payload = responseJson(response, 256 * 1024);
  if (!payload || payload.status !== "ready") {
    throw new Error("Staging readiness preflight failed; the load test was not started");
  }
}

let cursorInitialized = false;
let cursor = 0;
let cycle = 0;

export default function reconcileCursor() {
  const credential = credentials[exec.vu.idInTest - 1];
  if (!credential) fail("No unique credential was assigned to this virtual user");
  if (!cursorInitialized) {
    cursor = credential.cursor;
    cursorInitialized = true;
    sleep(Math.random() * syncIntervalSeconds);
  }

  const cycleStartedAt = Date.now();
  let page;
  let pageNumber = 0;
  do {
    page = getSyncPage(credential, cursor);
    if (!page) break;
    cursor = page.nextCursor;
    pageNumber += 1;
  } while (page.hasMore && pageNumber < maximumPagesPerCycle);

  if (page && page.hasMore) unconvergedCycles.add(1);
  if (cycle === 0 || cycle % manifestEveryCycles === 0) getManifest(credential, cursor);
  cycle += 1;

  const elapsedSeconds = (Date.now() - cycleStartedAt) / 1000;
  const jitterSeconds = (Math.random() - 0.5) * syncIntervalSeconds * 0.2;
  sleep(Math.max(0, syncIntervalSeconds + jitterSeconds - elapsedSeconds));
}
