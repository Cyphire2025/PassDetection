import assert from "node:assert/strict";
import test from "node:test";
import { currentUploadSources as source } from "./current-upload-source.contract-helper.mjs";

test("current file selection prepares a scoped preview before private upload", () => {
  assert.match(source.selection, /preparePublicUploadFile\(file, \{ token, uploadSessionId: sessionId/);
  assert.match(source.selection, /purpose: side === "photo" \? "visa" : "passport"/);
  assert.match(source.selection, /state\.upload\(side, ready\)/);
  assert.doesNotMatch(source.selection, /verifyUploadedVisaPhoto|prewarmUploadedVisaPhotoDetector/);
});

test("validated camera captures bypass file normalization and keep their capture bytes", () => {
  assert.match(source.selection, /source === "file" \? await preparePublicUploadFile[\s\S]*?: file;/);
  assert.match(source.documents, /startUpload\("photo", file, "camera"\)/);
  assert.match(source.selection, /visa_photo_source: source/);
});

test("one file transfer at a time prevents silently replacing an active request", () => {
  assert.match(source.selection, /if \(operation\.current\) return/);
  assert.match(source.selection, /operation\.current = controller/);
  assert.match(source.selection, /if \(controller\.signal\.aborted\) return/);
  assert.match(source.documents, /disabled=\{state\.pending \|\| preparing\}/);
});

test("selected document bytes stay in mounted state and are aborted on page exit", () => {
  assert.match(source.selection, /window\.addEventListener\("pagehide", leave\)/);
  assert.match(source.selection, /operation\.current\?\.abort\(\)/);
  assert.match(source.selection, /setSelected\(\{\}\)/);
  assert.doesNotMatch(source.selection, /sessionStorage|localStorage|JSON\.stringify\(file\)/);
});
