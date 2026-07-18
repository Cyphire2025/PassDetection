import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const apiSource = readFileSync(
  new URL("./upload-links.api.ts", import.meta.url),
  "utf8",
);
const endpointSource = readFileSync(
  new URL("../../../lib/api/endpoints.ts", import.meta.url),
  "utf8",
);
const telemetryHookSource = readFileSync(
  new URL("../../upload/hooks/use-public-flow-telemetry.ts", import.meta.url),
  "utf8",
);

test("telemetry uses the exact public token endpoint and upload-session header", () => {
  assert.match(
    endpointSource,
    /`\/api\/v1\/upload-links\/token\/\$\{token\}\/telemetry`/,
  );
  assert.match(
    apiSource,
    /"X-Upload-Session-ID": getOrCreatePublicUploadSessionId\(token\)/,
  );
  assert.match(
    apiSource,
    /recordTelemetry:[\s\S]*?API_ENDPOINTS\.uploadLinks\.telemetry\(token\),\s*payload,/,
  );
});

test("page exit uses fetch keepalive because beacon cannot carry the session header", () => {
  assert.match(
    apiSource,
    /recordTelemetryKeepalive:[\s\S]*?keepalive: true/,
  );
  assert.match(telemetryHookSource, /addEventListener\("pagehide"/);
  assert.match(telemetryHookSource, /event\.persisted/);
  assert.match(telemetryHookSource, /reason: "upload_abandoned"/);
});

test("recovery queue stores only validated fixed event and reason payloads", () => {
  assert.match(telemetryHookSource, /parseTelemetryQueue\(/);
  assert.match(telemetryHookSource, /enqueueTelemetry\(/);
  assert.doesNotMatch(
    telemetryHookSource,
    /\b(?:clientName|email|phone|passport|submissionId|userAgent)\b/,
  );
});
