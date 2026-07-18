import assert from "node:assert/strict";
import test from "node:test";
import {
  buildQualifierSelectionRequest,
  qualifierChoiceKey,
} from "./relation-qualifier.ts";

const options = [
  { code: "spouse", label: "Spouse" },
  { code: "legal_guardian", label: "Legal Guardian" },
];

test("Self is exclusive and never sends a relation", () => {
  assert.deepEqual(buildQualifierSelectionRequest("self", "spouse", options), {
    is_self: true,
    relation_code: null,
  });
  assert.equal(qualifierChoiceKey("self", "spouse"), "self");
});

test("an allowlisted relationship uses its stable canonical code", () => {
  assert.deepEqual(buildQualifierSelectionRequest("relation", "spouse", options), {
    is_self: false,
    relation_code: "spouse",
  });
  assert.equal(
    qualifierChoiceKey("relation", "legal_guardian"),
    "relation:legal_guardian",
  );
});

test("missing, Friend, arbitrary, and stale client options are rejected", () => {
  for (const relationCode of ["", "friend", "colleague", "other", "Spouse"]) {
    assert.equal(
      buildQualifierSelectionRequest("relation", relationCode, options),
      null,
    );
  }
  assert.equal(buildQualifierSelectionRequest(null, "", options), null);
});
