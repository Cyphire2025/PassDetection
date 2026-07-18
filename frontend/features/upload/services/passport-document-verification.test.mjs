import assert from "node:assert/strict";
import test from "node:test";
import {
  isAcceptedPassportDocument,
  passportDocumentVerificationGate,
} from "./passport-document-verification.ts";

function submission(aiVerification, errorMessage = null) {
  return {
    error_message: errorMessage,
    extracted_fields: aiVerification === undefined
      ? {}
      : { ai_verification: aiVerification },
  };
}

test("accepts only verified or enhanced with explicit availability", () => {
  assert.equal(isAcceptedPassportDocument({
    ai_verification: { status: "verified", available: true },
  }), true);
  assert.equal(isAcceptedPassportDocument({
    ai_verification: { status: "enhanced", available: true },
  }), true);
  assert.equal(isAcceptedPassportDocument({
    ai_verification: { status: "verified", available: false },
  }), false);
  assert.equal(isAcceptedPassportDocument({
    ai_verification: { status: "VERIFIED", available: true },
  }), false);
  assert.equal(isAcceptedPassportDocument({}), false);
});

test("provider, unavailable, and missing classifications require saved-image retry", () => {
  for (const value of [
    undefined,
    { status: "provider_unavailable", available: false },
    { status: "timeout", available: false },
    { status: "verified", available: false },
  ]) {
    const gate = passportDocumentVerificationGate(submission(value));
    assert.equal(gate.accepted, false);
    assert.equal(gate.action, "retry");
  }
});

test("wrong page and low-confidence document results require replacement", () => {
  for (const status of [
    "wrong_document",
    "passport_cover",
    "wrong_passport_page",
    "document_low_quality",
    "document_unreadable",
    "document_uncertain",
  ]) {
    const gate = passportDocumentVerificationGate(submission({
      status,
      available: false,
    }));
    assert.equal(gate.accepted, false);
    assert.equal(gate.action, "replace");
  }
});

test("uses the public server error message without exposing diagnostics", () => {
  const gate = passportDocumentVerificationGate(submission(
    { status: "wrong_document", available: false, model: "internal-model" },
    "Scan the passport photo and details page and try again.",
  ));
  assert.equal(
    gate.message,
    "Scan the passport photo and details page and try again.",
  );
  assert.equal(Object.hasOwn(gate, "model"), false);
});
