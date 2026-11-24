import assert from "node:assert/strict";
import test from "node:test";
import { currentUploadSources as source, readUploadSource } from "./current-upload-source.contract-helper.mjs";

test("current draft submission validates documents and fields before any completion request", () => {
  const validate = source.submission.indexOf("freshValidation(settings");
  const complete = source.submission.indexOf("await state.complete(proof.id)");
  assert.ok(validate >= 0 && complete > validate);
  assert.match(source.submission.slice(validate, complete), /if \(invalid\) return/);
  assert.match(source.submission.slice(validate, complete), /proof\.expiresAt <= Date\.now\(\)/);
  assert.match(source.documentValidation, /draft\.extraction_status !== "succeeded"/);
  assert.match(source.documentValidation, /document\.state === "ready"/);
  assert.match(source.documentValidation, /hasMissingRequiredFields\(payload\.passport_fields\)/);
  assert.match(source.documentValidation, /hasValidReviewDates\(payload\.passport_fields\)/);
});

test("verification reads the authoritative revision before exposing a proof", () => {
  const verify = source.contact.indexOf("await state.api.verifyCode");
  const refresh = source.contact.indexOf("await state.refresh()", verify);
  const adopt = source.contact.indexOf("setProof(next)", refresh);
  assert.ok(verify >= 0 && refresh > verify && adopt > refresh);
  assert.match(source.contact.slice(refresh, adopt), /signal\.throwIfAborted\(\)/);
});

test("server-rejected proofs can be renewed without resetting private fields or final keys", () => {
  assert.match(source.submission, /cause\.code === "verification_failed"/);
  assert.match(source.submission, /setRejectedProof\(proof\); setProof\(null\)/);
  assert.match(source.contact, /proof !== rejectedProof/);
  assert.doesNotMatch(source.submission, /clearDraftResume|sessionStorage|localStorage|submissionKey:/);
});

test("latest edits save before upload and completion and uncertain operation keys remain stable", () => {
  const upload = source.draft.indexOf("const upload =");
  const complete = source.draft.indexOf("const complete =");
  assert.match(source.draft.slice(upload, complete), /await save\(signal\)/);
  assert.match(source.draft.slice(complete), /saved\.current !== version\.current/);
  assert.match(source.draft.slice(complete), /member\.submissionKey/);
  assert.match(source.draft, /retryUpload\.current = request/);
  assert.match(source.draft, /retrySave\.current \?\?/);
});

test("failed extraction stays fail-closed while users correct fields or replace images", () => {
  assert.match(source.form, /state\.draft\.extraction_status === "failed"/);
  assert.match(source.form, /Replace the details page with a clearer image/);
  assert.match(source.documentValidation, /hasPassport && draft\.extraction_status !== "succeeded"/);
  assert.doesNotMatch(source.submission, /manual_review_submission_allowed|setStep\("SUCCESS"\)/);
});

test("current progress, errors and private save states remain accessible", () => {
  const shell = readUploadSource("./upload-flow-shell.tsx");
  const frame = readUploadSource("./document-processing-frame.tsx");
  const footer = readUploadSource("./fresh-submission-footer.tsx");
  assert.match(shell, /Loading secure upload/);
  assert.match(frame, /role="status"/);
  assert.match(footer, /role="alert"/);
  assert.match(footer, /state\.pending \|\| uploadBusy \|\| !verified/);
});

test("shared current passport fields keep surname and issue date optional", () => {
  const fields = readUploadSource("./upload-flow-review.tsx");
  const validation = readUploadSource("./upload-flow.constants.ts");
  assert.match(fields, /const isOptional = key === "date_of_issue" \|\| key === "surname"/);
  assert.match(fields, /required=\{!isOptional\}/);
  assert.match(validation, /field !== "date_of_issue" && field !== "surname"/);
});

test("current public header preserves the brand, travel details and bounded group name", () => {
  const header = readUploadSource("./upload-flow-shell.tsx");
  assert.match(header, /import \{ BrandLogo \} from "@\/components\/brand\/brand-logo"/);
  assert.match(header, /<BrandLogo[\s\S]*?priority/);
  assert.match(header, /Prepare your documents for a smooth journey/);
  assert.match(header, /<span className="truncate">\{groupName\}<\/span>/);
});
