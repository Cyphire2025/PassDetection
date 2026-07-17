import assert from "node:assert/strict";
import test from "node:test";
import { isPassportWorkflowPending } from "./passport-workflow.ts";

test("polls every asynchronous workflow status", () => {
  for (const status of ["processing", "pending_extraction", "extracting", "submitted"]) {
    assert.equal(isPassportWorkflowPending(status), true, status);
  }
});

test("continues polling legacy extraction processing", () => {
  assert.equal(isPassportWorkflowPending("client_submitted", "processing"), true);
});

test("stops polling terminal review and approval statuses", () => {
  for (const status of [
    "ready_for_client_review",
    "ai_approved",
    "needs_review",
    "staff_approved",
    "failed",
  ]) {
    assert.equal(isPassportWorkflowPending(status), false, status);
  }
});
