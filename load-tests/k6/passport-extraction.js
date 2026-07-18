import { check, fail, sleep } from "k6";
import http from "k6/http";
import { Counter, Rate, Trend } from "k6/metrics";

const BASE_URL = (__ENV.BASE_URL || "https://localhost").replace(/\/$/, "");
const UPLOAD_TOKEN = __ENV.UPLOAD_TOKEN || "";
const FIXTURE_MANIFEST = __ENV.FIXTURE_MANIFEST || "./fixtures/manifest.json";
const POLL_TIMEOUT_MS = Number(__ENV.POLL_TIMEOUT_MS || 45000);
const POLL_INTERVAL_MS = Number(__ENV.POLL_INTERVAL_MS || 1000);
const IDEMPOTENCY_PROBE = __ENV.IDEMPOTENCY_PROBE !== "false";

const manifest = JSON.parse(open(FIXTURE_MANIFEST));
if (!UPLOAD_TOKEN) {
  fail("UPLOAD_TOKEN is required");
}
if (!Array.isArray(manifest) || manifest.length < 100) {
  fail("FIXTURE_MANIFEST must contain at least 100 approved non-production fixture pairs");
}

const selectedManifest = manifest.slice(0, 100);
const distinctFixturePairs = new Set(
  selectedManifest.map((entry) => `${entry.front || ""}\u0000${entry.back || ""}`),
);
if (distinctFixturePairs.size !== 100) {
  fail("The first 100 manifest entries must reference 100 distinct front/back fixture pairs");
}

const fixtures = selectedManifest.map((entry, index) => {
  if (!entry.front || !entry.back) {
    fail(`Fixture ${index} must contain front and back paths`);
  }
  return {
    front: open(entry.front, "b"),
    back: open(entry.back, "b"),
    frontName: entry.frontName || `passport-front-${index + 1}.jpg`,
    backName: entry.backName || `passport-back-${index + 1}.jpg`,
  };
});

const successfulExtractions = new Counter("successful_extractions");
const completeExtractions = new Counter("complete_extractions");
const partialExtractions = new Counter("partial_extractions");
const manualFallbackExtractions = new Counter("manual_fallback_extractions");
const failedExtractions = new Counter("failed_extractions");
const rateLimitedResponses = new Counter("rate_limited_responses");
const proxyFailures = new Counter("proxy_failures");
const uploadFailures = new Counter("upload_failures");
const bootstrapFailures = new Counter("bootstrap_failures");
const pollRetries = new Counter("poll_retries");
const duplicateSubmissions = new Counter("duplicate_submissions");
const extractionLatency = new Trend("extraction_latency", true);
const uploadLatency = new Trend("upload_latency", true);
const extractionSuccessRate = new Rate("extraction_success_rate");

export const options = {
  scenarios: {
    interactive_extraction_burst: {
      executor: "per-vu-iterations",
      vus: 100,
      iterations: 1,
      maxDuration: "2m",
      gracefulStop: "5s",
    },
  },
  thresholds: {
    extraction_success_rate: ["rate==1"],
    successful_extractions: ["count==100"],
    complete_extractions: ["count==100"],
    partial_extractions: ["count==0"],
    manual_fallback_extractions: ["count==0"],
    failed_extractions: ["count==0"],
    rate_limited_responses: ["count==0"],
    proxy_failures: ["count==0"],
    upload_failures: ["count==0"],
    bootstrap_failures: ["count==0"],
    duplicate_submissions: ["count==0"],
    extraction_latency: ["p(99)<40000"],
  },
  insecureSkipTLSVerify: __ENV.INSECURE_SKIP_TLS_VERIFY === "true",
  noConnectionReuse: false,
  userAgent: "PassDetection-k6-approved-non-production-load-test/1.0",
};

function requestHeaders(sessionId) {
  return {
    "X-Upload-Session-ID": sessionId,
    "X-Load-Test-ID": __ENV.LOAD_TEST_ID || "local-controlled-run",
  };
}

function recordHttpFailure(response) {
  if (response.status === 429) {
    let code = "unknown";
    try {
      code = response.json("error.code") || "unknown";
    } catch {
      // An invalid proxy body is itself visible through the unknown tag.
    }
    rateLimitedResponses.add(1, {
      origin: code.startsWith("PROXY_") ? "proxy" : "application",
      code,
    });
  }
  if (response.status === 502 || response.status === 503 || response.status === 504) {
    proxyFailures.add(1, { status: String(response.status) });
  }
}

function terminal(payload) {
  return [
    "extraction_complete",
    "extraction_partial",
    "extraction_failed",
    "ready_for_review",
  ].includes(payload.extraction_status)
    || ["ready_for_client_review", "review_required", "failed"].includes(payload.status);
}

function extractionOutcome(payload) {
  if (payload.extraction_status === "extraction_complete") {
    return "complete";
  }
  if (payload.extraction_status === "extraction_partial") {
    return "partial";
  }
  if (payload.extraction_status === "ready_for_review") {
    return "manual_fallback";
  }
  return "failed";
}

export default function () {
  const fixture = fixtures[(__VU - 1) % fixtures.length];
  const sessionId = `k6-${__VU}-${__ITER}-${Date.now()}`;
  const bootstrapSessionId = `${sessionId}-bootstrap`;
  const idempotencyKey = `${sessionId}-upload`;
  const uploadStarted = Date.now();
  const bootstrapResponse = http.get(
    `${BASE_URL}/api/v1/upload-links/token/${UPLOAD_TOKEN}`,
    {
      headers: requestHeaders(bootstrapSessionId),
      timeout: "12s",
      tags: { operation: "upload_link_bootstrap" },
    },
  );
  recordHttpFailure(bootstrapResponse);
  if (!check(bootstrapResponse, {
    "upload link bootstrap loaded": (response) => response.status === 200,
  })) {
    bootstrapFailures.add(1, { status: String(bootstrapResponse.status) });
    failedExtractions.add(1, {
      phase: "bootstrap",
      status: String(bootstrapResponse.status),
    });
    extractionSuccessRate.add(false);
    return;
  }

  const uploadResponse = http.post(
    `${BASE_URL}/api/v1/passports/upload/${UPLOAD_TOKEN}`,
    {
      client_name: `Load Fixture ${String(__VU).padStart(3, "0")}`,
      acquisition_mode: "camera",
      upload_idempotency_key: idempotencyKey,
      file: http.file(fixture.front, fixture.frontName, "image/jpeg"),
      passport_back_file: http.file(fixture.back, fixture.backName, "image/jpeg"),
    },
    {
      headers: requestHeaders(idempotencyKey),
      timeout: "65s",
      tags: { operation: "initial_upload" },
    },
  );
  uploadLatency.add(Date.now() - uploadStarted);
  recordHttpFailure(uploadResponse);

  if (!check(uploadResponse, {
    "upload persisted": (response) => response.status === 201,
  })) {
    uploadFailures.add(1, { status: String(uploadResponse.status) });
    failedExtractions.add(1, { phase: "upload", status: String(uploadResponse.status) });
    extractionSuccessRate.add(false);
    return;
  }

  const uploaded = uploadResponse.json();
  if (!uploaded || !uploaded.id) {
    failedExtractions.add(1, { phase: "upload_contract" });
    extractionSuccessRate.add(false);
    return;
  }

  const seenSubmissionIds = new Set([uploaded.id]);

  let current = uploaded;
  const deadline = uploadStarted + POLL_TIMEOUT_MS;
  while (!terminal(current) && Date.now() < deadline) {
    sleep(POLL_INTERVAL_MS / 1000);
    const pollResponse = http.get(
      `${BASE_URL}/api/v1/passports/upload/${UPLOAD_TOKEN}/${uploaded.id}/status`,
      {
        headers: requestHeaders(uploaded.id),
        timeout: "12s",
        tags: { operation: "extraction_status" },
      },
    );
    recordHttpFailure(pollResponse);
    if (pollResponse.status !== 200) {
      pollRetries.add(1, { status: String(pollResponse.status) });
      continue;
    }
    current = pollResponse.json();
    if (current && current.id) {
      seenSubmissionIds.add(current.id);
    }
  }

  const elapsed = Date.now() - uploadStarted;
  extractionLatency.add(elapsed);

  // Run replay probes only after the extraction burst has drained. Sending
  // ten extra multipart requests during the same 1-2 second arrival window
  // would test an unintended 110-user proxy burst instead of the required
  // 100-user extraction target.
  if (IDEMPOTENCY_PROBE && __VU % 10 === 0) {
    const replay = http.post(
      `${BASE_URL}/api/v1/passports/upload/${UPLOAD_TOKEN}`,
      {
        client_name: `Load Fixture ${String(__VU).padStart(3, "0")}`,
        acquisition_mode: "camera",
        upload_idempotency_key: idempotencyKey,
        file: http.file(fixture.front, fixture.frontName, "image/jpeg"),
        passport_back_file: http.file(fixture.back, fixture.backName, "image/jpeg"),
      },
      {
        headers: requestHeaders(idempotencyKey),
        timeout: "65s",
        tags: { operation: "idempotent_upload_replay" },
      },
    );
    recordHttpFailure(replay);
    if (replay.status !== 201 || replay.json("id") !== uploaded.id) {
      duplicateSubmissions.add(1, { phase: "idempotency_replay" });
    }
  }

  if (seenSubmissionIds.size !== 1) {
    duplicateSubmissions.add(1);
  }

  const outcome = extractionOutcome(current);
  if (outcome === "complete") completeExtractions.add(1);
  if (outcome === "partial") partialExtractions.add(1);
  if (outcome === "manual_fallback") manualFallbackExtractions.add(1);

  if (
    terminal(current)
    && outcome === "complete"
    && seenSubmissionIds.size === 1
  ) {
    successfulExtractions.add(1);
    extractionSuccessRate.add(true);
  } else {
    failedExtractions.add(1, {
      phase: terminal(current) ? "processing" : "timeout",
      status: String(current?.status || "unknown"),
    });
    extractionSuccessRate.add(false);
  }
}
