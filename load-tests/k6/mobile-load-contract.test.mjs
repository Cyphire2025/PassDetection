import assert from "node:assert/strict";
import test from "node:test";

import {
  boundedIntegerSetting,
  maximumVus,
  stagesForProfile,
  validateCredentialEntries,
  validateLoadEnvironment,
} from "./mobile-load-contract.mjs";

const validEnvironment = () => ({
  BASE_URL: "https://mobile-staging.example.com/api/v1",
  LOAD_TEST_APPROVAL_REFERENCE: "change-12345",
  LOAD_TEST_APPROVED: "true",
  LOAD_TEST_EXPECTED_ORIGIN: "https://mobile-staging.example.com",
  LOAD_TEST_ID: "mobile-rc-2026-08-19",
  LOAD_TEST_PRODUCTION_ORIGIN: "https://mobile.example.com",
  LOAD_TEST_TARGET_ENVIRONMENT: "staging",
  MOBILE_LOAD_PROFILE: "1k",
});

const credential = (tokenSuffix = "a") => ({
  access_token: `test-only-${tokenSuffix.padEnd(40, "x")}`,
  cursor: 42,
  trip_id: "11111111-1111-4111-8111-111111111111",
});

test("the 1k profile represents 1,000 stateful virtual users", () => {
  const stages = stagesForProfile("1k");
  assert.equal(maximumVus(stages), 1000);
  assert.deepEqual(stages[1], { duration: "60m", target: 1000 });
});

test("the target contract accepts an exact, separately identified staging origin", () => {
  const contract = validateLoadEnvironment(validEnvironment());
  assert.equal(contract.baseUrl, "https://mobile-staging.example.com/api/v1");
  assert.equal(contract.profile, "1k");
});

test("the target contract rejects a production target and an origin mismatch", () => {
  const production = validEnvironment();
  production.LOAD_TEST_EXPECTED_ORIGIN = production.LOAD_TEST_PRODUCTION_ORIGIN;
  production.BASE_URL = `${production.LOAD_TEST_PRODUCTION_ORIGIN}/api/v1`;
  assert.throws(() => validateLoadEnvironment(production), /must be different/);

  const mismatch = validEnvironment();
  mismatch.BASE_URL = "https://another-staging.example.com/api/v1";
  assert.throws(() => validateLoadEnvironment(mismatch), /must exactly match/);

  const defaultPortAlias = validEnvironment();
  defaultPortAlias.LOAD_TEST_EXPECTED_ORIGIN = "https://mobile.example.com:0443";
  defaultPortAlias.BASE_URL = "https://mobile.example.com/api/v1";
  assert.throws(() => validateLoadEnvironment(defaultPortAlias), /must be different/);

  const wrongPathCase = validEnvironment();
  wrongPathCase.BASE_URL = "https://mobile-staging.example.com/API/V1";
  assert.throws(() => validateLoadEnvironment(wrongPathCase), /must exactly match/);
});

test("the target contract fails closed without staging approval metadata", () => {
  for (const key of [
    "LOAD_TEST_APPROVED",
    "LOAD_TEST_TARGET_ENVIRONMENT",
    "LOAD_TEST_APPROVAL_REFERENCE",
  ]) {
    const environment = validEnvironment();
    delete environment[key];
    assert.throws(() => validateLoadEnvironment(environment));
  }
});

test("credential validation enforces one token per virtual user without leaking it", () => {
  const secret = credential("private-session-secret");
  let error;
  try {
    validateCredentialEntries([secret, secret], 2);
  } catch (caught) {
    error = caught;
  }
  assert.ok(error instanceof Error);
  assert.match(error.message, /unique session/);
  assert.equal(error.message.includes(secret.access_token), false);
});

test("credential validation normalizes valid fixtures and rejects invalid cursors", () => {
  assert.deepEqual(validateCredentialEntries([credential()], 1)[0], {
    accessToken: credential().access_token,
    cursor: 42,
    tripId: "11111111-1111-4111-8111-111111111111",
    tripIds: ["11111111-1111-4111-8111-111111111111"],
  });
  assert.throws(
    () => validateCredentialEntries([{ ...credential(), cursor: -1 }], 1),
    /entry 0 is invalid/,
  );
});

test("credential validation models every trip authorized for realtime hints", () => {
  const entry = {
    ...credential(),
    authorized_trip_ids: [
      "11111111-1111-4111-8111-111111111111",
      "22222222-2222-4222-8222-222222222222",
    ],
  };
  assert.deepEqual(validateCredentialEntries([entry], 1)[0].tripIds, entry.authorized_trip_ids);
  assert.throws(
    () => validateCredentialEntries([{
      ...entry,
      authorized_trip_ids: ["22222222-2222-4222-8222-222222222222"],
    }], 1),
    /including trip_id/,
  );
});

test("bounded integer settings reject ambiguous and unsafe values", () => {
  assert.equal(boundedIntegerSetting(undefined, 30, 5, 300, "INTERVAL"), 30);
  assert.equal(boundedIntegerSetting("60", 30, 5, 300, "INTERVAL"), 60);
  assert.throws(() => boundedIntegerSetting("1.5", 30, 5, 300, "INTERVAL"));
  assert.throws(() => boundedIntegerSetting("301", 30, 5, 300, "INTERVAL"));
});
