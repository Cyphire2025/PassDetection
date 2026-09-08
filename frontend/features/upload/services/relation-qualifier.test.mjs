import assert from "node:assert/strict";
import test from "node:test";
import {
  buildQualifierSelectionRequest,
  qualifierChoiceKey,
  qualifierOtherRelationError,
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

const bothMethods = { listEnabled: true, otherEnabled: true };

test("Other sends only its normalized text and ignores a previously selected list value", () => {
  assert.deepEqual(
    buildQualifierSelectionRequest("other", "spouse", options, "  Family friend  ", bothMethods),
    { is_self: false, relation_code: "other", other_relation: "Family friend" },
  );
  assert.deepEqual(
    buildQualifierSelectionRequest("other", "", options, "Frie\u0301nd", bothMethods),
    { is_self: false, relation_code: "other", other_relation: "Friénd" },
  );
});

test("disabled methods reject stale values and existing links retain list-only behavior", () => {
  assert.equal(buildQualifierSelectionRequest("other", "", options, "Friend"), null);
  assert.equal(
    buildQualifierSelectionRequest("relation", "spouse", options, "", {
      listEnabled: false, otherEnabled: true,
    }),
    null,
  );
  assert.equal(
    buildQualifierSelectionRequest("other", "", options, "Friend", {
      listEnabled: true, otherEnabled: false,
    }),
    null,
  );
  assert.deepEqual(
    buildQualifierSelectionRequest("self", "spouse", options, "Friend", {
      listEnabled: false, otherEnabled: false,
    }),
    { is_self: true, relation_code: null },
  );
});

test("list and Self payloads do not carry stale Other text", () => {
  assert.deepEqual(
    buildQualifierSelectionRequest("relation", "spouse", options, "Friend", bothMethods),
    { is_self: false, relation_code: "spouse" },
  );
  assert.deepEqual(
    buildQualifierSelectionRequest("self", "", options, "Friend", bothMethods),
    { is_self: true, relation_code: null },
  );
});

test("Other rejects missing, reserved, multiline, and hidden-control text", () => {
  for (const invalid of ["", "  ", " self ", "SELF", "Friend\ncolleague", "F\u0000riend", "F\u007friend", "F\u0085riend", "F\u200briend", "Friend\u2028colleague", "Friend\u2029colleague"]) {
    assert.ok(qualifierOtherRelationError(invalid), JSON.stringify(invalid));
    assert.equal(
      buildQualifierSelectionRequest("other", "", options, invalid, bothMethods),
      null,
      JSON.stringify(invalid),
    );
  }
});

test("Other length matches server Unicode codepoint validation", () => {
  for (const value of ["F".repeat(100), "é".repeat(100), "𐐀".repeat(100)]) {
    assert.equal(qualifierOtherRelationError(value), null);
  }
  assert.equal(qualifierOtherRelationError("F".repeat(101)), "Use 100 characters or fewer.");
  assert.equal(qualifierOtherRelationError("𐐀".repeat(101)), "Use 100 characters or fewer.");
});

test("editing Other invalidates its saved choice while canonical-equivalent text does not", () => {
  assert.equal(qualifierChoiceKey("other", "spouse", "  Friend  "), "other:Friend");
  assert.notEqual(qualifierChoiceKey("other", "", "Friend"), qualifierChoiceKey("other", "", "Colleague"));
  assert.equal(qualifierChoiceKey("other", "", "Frie\u0301nd"), qualifierChoiceKey("other", "", "Friénd"));
  assert.notEqual(qualifierChoiceKey("relation", "spouse"), qualifierChoiceKey("other", "", "spouse"));
});
