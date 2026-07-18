import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("./passport-group-detail.tsx", import.meta.url),
  "utf8",
);

test("group confidence uses post-submission verification instead of extraction", () => {
  assert.match(
    source,
    /function getGroupVerificationConfidence\(passport: PassportSubmission\)/,
  );
  assert.match(
    source,
    /getPassportVerificationConfidence\(verification\)/,
  );
  assert.match(
    source,
    /formatConfidence\(getGroupVerificationConfidence\(passport\)\)/,
  );
  assert.doesNotMatch(
    source,
    /formatConfidence\(passport\.overall_confidence\)/,
  );
});

test("low-confidence filter excludes rows without completed verification", () => {
  assert.match(
    source,
    /qualityFilter === "low_confidence"[\s\S]*?\(confidence === null \|\| confidence > 0\.5\)/,
  );
});
