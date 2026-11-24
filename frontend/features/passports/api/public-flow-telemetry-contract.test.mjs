import { uploadLinkApiSource as apiSource } from "./upload-link-api-source.contract-helper.mjs";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";


const endpointSource = readFileSync(
  new URL("../../../lib/api/endpoints.ts", import.meta.url),
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

test("retained telemetry facade supports keepalive while preserving the private session header", () => {
  assert.match(apiSource, /recordTelemetryKeepalive:[\s\S]*?keepalive: true/);
  assert.match(apiSource, /"X-Upload-Session-ID": getOrCreatePublicUploadSessionId\(token\)/);
});
