import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("./upload-flow.tsx", import.meta.url),
  "utf8",
);

test("initialization cleanup permits React effect replay", () => {
  assert.match(
    source,
    /if \(initializedGroupTokenRef\.current === token\) \{\s*initializedGroupTokenRef\.current = null;/,
  );
});

test("resume state is cleared before leaving the upload step", () => {
  const successStart = source.indexOf(".then((result) => {");
  const resumeClear = source.indexOf("clearResumeState();", successStart);
  const reviewStep = source.indexOf('setStep("REVIEW")', resumeClear);

  assert.ok(successStart >= 0);
  assert.ok(resumeClear > successStart);
  assert.ok(reviewStep > resumeClear);
  assert.match(
    source,
    /if \(resumeInFlightRef\.current !== savedSubmission\.id\) return;/,
  );
});

test("scan-again requests have a synchronous single-flight guard", () => {
  assert.match(
    source,
    /isScanningAgain \|\| scanAgainInFlightRef\.current/,
  );
  assert.match(source, /scanAgainInFlightRef\.current = true;/);
  assert.match(source, /scanAgainInFlightRef\.current = false;/);
});

test("camera cancellation and stable rejection reasons use fixed telemetry events", () => {
  assert.match(source, /event: "passport_scanner_rejection"/);
  assert.match(source, /event: "visa_photo_rejection"/);
  assert.match(source, /reason: "camera_cancelled"/);
  assert.match(source, /reportPublicFlowOnce\("recovery_started"\)/);
  assert.match(source, /reportPublicFlowOnce\("recovery_succeeded"\)/);
  assert.match(source, /reportPublicFlowOnce\("recovery_missed"\)/);
});

test("single and family submission handlers fail closed on document verification", () => {
  const singleStart = source.indexOf("const handleFinalSubmit");
  const familyStart = source.indexOf("const handleFamilySubmit");
  const singleGate = source.indexOf(
    "passportDocumentVerificationGate(submission)",
    singleStart,
  );
  const singleSubmit = source.indexOf("await submitClientReview", singleStart);
  const familyGate = source.indexOf(
    "const blockedVerification = familyMembers.find",
    familyStart,
  );
  const familySubmit = source.indexOf("await submitClientReview", familyStart);

  assert.ok(singleStart >= 0);
  assert.ok(singleGate > singleStart && singleGate < singleSubmit);
  assert.ok(familyGate > familyStart && familyGate < familySubmit);
});

test("unverified single and family records render recovery actions, not submit controls", () => {
  assert.match(
    source,
    /!verificationGate\.accepted \? \(\s*<div[\s\S]*?<DocumentVerificationBlock/,
  );
  assert.match(
    source,
    /!verificationGate\.accepted \? \(\s*<DocumentVerificationBlock/,
  );
  assert.match(source, /gate\.action === "retry" \? onRetry : onReplace/);
  assert.match(source, /!hasBlockedFamilyVerification \? \(/);
});

test("restored and response-loss submissions return through the same gated review state", () => {
  assert.match(
    source,
    /setSubmission\(result\.submission\);[\s\S]*?setStep\("REVIEW"\)/,
  );
  assert.match(
    source,
    /setSubmission\(persisted\);[\s\S]*?setStep\("REVIEW"\)/,
  );
});

test("a durable saved submission is restored before qualifier token recovery", () => {
  const reconciliation = source.indexOf(
    "const recoveryTarget = uploadRecoveryTarget",
  );
  const durableRestore = source.indexOf(
    "if (recovery.submissionId)",
    reconciliation,
  );
  const qualifierRestore = source.indexOf(
    "const storedToken = readQualifierSelectionToken",
    durableRestore,
  );
  const restoreBlock = source.slice(durableRestore, qualifierRestore);

  assert.ok(reconciliation >= 0);
  assert.ok(durableRestore > reconciliation);
  assert.ok(qualifierRestore > durableRestore);
  assert.match(restoreBlock, /setFlowMode\("single"\)/);
  assert.match(
    restoreBlock,
    /await restoreSubmission\(recovery\.submissionId\)/,
  );
});

test("loading, failure, processing, and completion states are announced", () => {
  assert.match(source, /<span className="sr-only">Loading secure upload<\/span>/);
  assert.match(source, /function ErrorMessage[\s\S]*?role="alert"/);
  assert.match(source, /function ProcessingScreen[\s\S]*?aria-busy="true"/);
  assert.match(source, /role="progressbar"/);
  assert.match(source, /aria-valuenow=\{progressPercent\}/);
  assert.match(
    source,
    /step === "SUCCESS"[\s\S]*?role="status"[\s\S]*?aria-live="polite"/,
  );
});

test("surname may be blank while every other canonical field remains required", () => {
  assert.match(
    source,
    /field !== "date_of_issue" && field !== "surname"/,
  );
  assert.match(
    source,
    /const isOptional = key === "date_of_issue" \|\| key === "surname";/,
  );
  assert.match(
    source,
    /placeholder=\{key === "surname" \? "Leave blank if not present" : "Not extracted"\}/,
  );
  assert.match(source, /required=\{!isOptional\}/);
  assert.match(
    source,
    /cleanPassportReviewFields as cleanReviewFields/,
  );
  assert.equal(
    source.match(/confirmed_fields: cleanReviewFields\(/g)?.length,
    2,
    "single and family submissions must use the explicit-empty-aware cleaner",
  );
});

test("public upload entry uses Global Connect branding and requested copy", () => {
  assert.match(
    source,
    /import \{ BrandLogo \} from "@\/components\/brand\/brand-logo";/,
  );
  assert.match(source, /<BrandLogo[\s\S]*?priority[\s\S]*?\/>/);
  assert.match(
    source,
    /Global Connect Travels has requested passport details for/,
  );
  assert.match(source, />Upload Travel Documents<\/h1>/);
  assert.match(
    source,
    /title=\{file \? "Visa Photo ready" : "Upload Photo for Visa"\}/,
  );
  assert.doesNotMatch(
    source,
    /Your travel agency has requested passport details for|Capture Visa Photo/,
  );
});
