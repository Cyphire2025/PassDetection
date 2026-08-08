import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (file) => readFileSync(new URL(file, import.meta.url), "utf8");
const orchestrator = read("./upload-flow.tsx");
const bootstrapSource = read("../services/upload-flow-bootstrap.ts");
const helperSource = read("../services/upload-flow-helpers.ts");
const sessionSource = read("../services/upload-flow-session.ts");

test("the upload orchestrator delegates state-independent UI and helpers", () => {
  for (const moduleName of [
    "upload-flow-fields",
    "upload-flow-passport-picker",
    "upload-flow-review",
    "upload-flow-shell",
    "upload-flow-helpers",
    "upload-flow-bootstrap",
    "upload-flow-session",
  ]) {
    assert.match(orchestrator, new RegExp(`from [^;]*${moduleName}`));
  }

  assert.doesNotMatch(
    orchestrator,
    /function (UploadHeader|PassportDocumentBundlePanel|ReviewFields|createFamilyMember|createIdempotencyKey)\b/,
  );
  assert.doesNotMatch(orchestrator, /const restoreSubmission = async/);
  assert.match(bootstrapSource, /const restoreSubmission = async/);
});

test("bootstrap recovery is a React-independent controller boundary", () => {
  assert.match(bootstrapSource, /export async function runUploadFlowBootstrap/);
  assert.match(orchestrator, /void runUploadFlowBootstrap\(\{/);
  assert.doesNotMatch(bootstrapSource, /from "react"|useEffect|useState|useRef/);
  assert.match(orchestrator, /isCancelled: \(\) => cancelled/);
  assert.match(orchestrator, /queueSubmissionResume: \(savedSubmission\) =>/);
});

test("camera, crop, and visa capture remain lazy boundaries", () => {
  for (const component of [
    "passport-manual-crop",
    "smart-camera",
    "visa-photo-upload",
    "visa-selfie-camera",
  ]) {
    assert.match(
      orchestrator,
      new RegExp(`dynamic\\(\\s*\\(\\) => import\\("\\./${component}"\\)`),
    );
  }
});

test("family resizing has one pure implementation", () => {
  assert.equal(orchestrator.match(/resizeFamilyMembers\(/g)?.length, 2);
  assert.doesNotMatch(orchestrator, /while \(next\.length/);
  assert.match(helperSource, /export function resizeFamilyMembers/);
});

test("private recovery keys and secure idempotency stay isolated in the session service", () => {
  assert.match(sessionSource, /gct:upload-recovery:/);
  assert.match(sessionSource, /gct:qualifier-selection:/);
  assert.match(sessionSource, /crypto\.getRandomValues/);
  assert.doesNotMatch(sessionSource, /Math\.random/);
});
