import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("./passport-detail.tsx", import.meta.url),
  "utf8",
);
const hooksSource = readFileSync(
  new URL("../hooks/use-passports.ts", import.meta.url),
  "utf8",
);

test("manual approval sends the rendered revision and optional reason", () => {
  assert.match(
    source,
    /buildStaffApprovalRequest\(\s*fields,\s*data\.extraction_revision,\s*reviewReason,/,
  );
  assert.match(source, /maxLength=\{240\}/);
});

test("manual approval cannot be repeated while its mutation is pending", () => {
  assert.match(
    source,
    /isSaving=\{confirmMutation\.isPending \|\| staffApproveMutation\.isPending\}/,
  );
  assert.match(
    source,
    /if \(isSaving \|\| reviewActionInFlightRef\.current\) return;/,
  );
  assert.match(source, /reviewActionInFlightRef\.current = true;/);
  assert.match(source, /reviewActionInFlightRef\.current = false;/);
});

test("approval, verification retry, and re-extraction are mutually exclusive", () => {
  assert.match(
    source,
    /actionState\.disabled\s*\|\| isRetryingAiVerification\s*\|\| isReextracting/,
  );
  assert.match(
    source,
    /isRetryingAiVerification \|\| isSaving \|\| isReextracting/,
  );
  assert.match(
    source,
    /isRetryingAiVerification\s*\|\| verificationRetryInFlightRef\.current/,
  );
  assert.match(
    source,
    /passport\.extraction_status === "processing"\s*\|\| isSaving\s*\|\| isRetryingAiVerification/,
  );
});

test("a stale approval refreshes the record and remounts review state by revision", () => {
  assert.match(
    hooksSource,
    /feedback\.kind === "record_changed"[\s\S]*?invalidateQueries\(\{\s*queryKey: QUERY_KEYS\.passports\.detail\(id\)/,
  );
  assert.match(
    source,
    /key=\{`\$\{data\.id\}:\$\{data\.extraction_revision\}:\$\{data\.updated_at\}`\}/,
  );
  assert.match(source, /\{formError && \(\s*<div role="alert"/);
});

test("review fields show verification confidence without extraction confidence", () => {
  assert.doesNotMatch(source, /label="Extraction confidence"/);
  assert.match(source, /label="Verification confidence"/);
  assert.match(source, /getPassportVerificationConfidence/);
});

test("client-provided details show the submitted email and phone", () => {
  assert.match(source, /\["Email entered by client", passport\.client_email\]/);
  assert.match(source, /\["Phone entered by client", passport\.client_phone\]/);
});
