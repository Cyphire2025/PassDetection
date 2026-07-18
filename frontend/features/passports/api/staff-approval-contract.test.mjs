import assert from "node:assert/strict";
import test from "node:test";
import {
  parseStaffApprovalResponse,
  serializeStaffApprovalRequest,
} from "./staff-approval-contract.ts";

test("serializes revision, corrections, and trimmed optional reason", () => {
  assert.deepEqual(
    serializeStaffApprovalRequest({
      confirmedFields: { passport_number: "P1234567" },
      expectedExtractionRevision: 9,
      reviewReason: "  Manual visual check. ",
    }),
    {
      confirmed_fields: { passport_number: "P1234567" },
      expected_extraction_revision: 9,
      review_reason: "Manual visual check.",
    },
  );
});

test("reads explicit approval outcomes without changing submission shape", () => {
  const submission = {
    id: "submission-id",
    extraction_revision: 10,
  };
  const result = parseStaffApprovalResponse(
    submission,
    {
      "x-staff-approval-outcome": "already_approved",
      "x-staff-approval-revision": "11",
    },
  );

  assert.equal(result.submission, submission);
  assert.equal(result.outcome, "already_approved");
  assert.equal(result.extractionRevision, 11);
});
