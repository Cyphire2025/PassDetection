import assert from "node:assert/strict";
import test from "node:test";
import { currentUploadSources as source } from "./current-upload-source.contract-helper.mjs";

test("the primary portal query directly owns the recoverable error presentation", () => {
  assert.equal(source.portal.match(/useUploadLinkByToken\(token\)/g)?.length, 1);
  assert.match(source.portal, /if \(error \|\| !group\) return <UploadLinkErrorScreen/);
  assert.match(source.portal, /refetch\(\{ cancelRefetch: false \}\)/);
  assert.doesNotMatch(source.portal, /import\("\.\/upload-flow"\)|<UploadFlow|readUploadRecoveryRecord/);
});

test("current Fresh, returning and camera entry points remain literal lazy boundaries", () => {
  assert.match(source.portal, /dynamic\(\(\) => import\("\.\/fresh-flow"\)/);
  assert.match(source.portal, /import\("@\/features\/travellers\/components\/returning-flow"\)/);
  for (const camera of ["smart-camera", "visa-selfie-camera"]) {
    assert.ok(source.documents.includes(`dynamic(() => import("./${camera}")`), `${camera} is loaded only for active capture`);
  }
});

test("one revision queue serializes each current fresh and returning private draft", () => {
  for (const draft of [source.draft, source.returning]) {
    assert.match(draft, /queue\.current\.catch\(\(\) => undefined\)\.then/);
    assert.match(draft, /signal\.aborted/);
    assert.match(draft, /useDraftInitialization\(/);
    assert.match(draft, /sendDraftUpload\(/);
  }
});

test("initialization shares StrictMode starts and cancels abandoned member visits", () => {
  assert.match(source.initialization, /request\.current\?\.scope !== scope/);
  assert.match(source.initialization, /promise: load\(controller\.signal\)/);
  assert.match(source.initialization, /!active\.signal\.aborted && !started\.delivered/);
  assert.match(source.initialization, /if \(!started\.consumers\) started\.controller\.abort\(\)/);
});

test("browser resume storage retains only navigation and opaque operation identities", () => {
  const start = source.resume.indexOf("export function saveFreshResume");
  const save = source.resume.slice(start);
  assert.match(save, /members: fresh\.members\.map\(\(\{ sessionId, submissionKey, completed \}\)/);
  assert.doesNotMatch(save, /client_email|client_phone|passport_fields|documents:/);
  assert.match(source.fresh, /sessionId: crypto\.randomUUID\(\)/);
  assert.match(source.fresh, /submissionKey: crypto\.randomUUID\(\)/);
});
