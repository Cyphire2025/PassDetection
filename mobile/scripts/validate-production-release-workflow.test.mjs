import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { parseDocument } from 'yaml';

const require = createRequire(import.meta.url);
const { validateProductionReleaseWorkflow } = require('./validate-maestro-workspace.js');
const baseline = parseDocument(
  readFileSync(new URL('../.eas/workflows/production-release.yml', import.meta.url), 'utf8'),
).toJS();

function changed(mutator) {
  const workflow = structuredClone(baseline);
  mutator(workflow);
  return validateProductionReleaseWorkflow(workflow);
}

test('accepts the exact reviewed production release graph', () => {
  assert.deepEqual(validateProductionReleaseWorkflow(structuredClone(baseline)), []);
});

test('rejects artifact substitution and signer-verification bypasses', () => {
  assert.ok(changed((workflow) => {
    workflow.jobs.verify_android_bundle.steps[1].with.build_id = 'different-build';
  }).some((message) => message.includes('exact signed build')));

  assert.ok(changed((workflow) => {
    workflow.jobs.build_android.needs = workflow.jobs.build_android.needs
      .filter((jobId) => jobId !== 'verify_android_signed_smoke');
  }).some((message) => message.includes('mandatory Android gate')));

  assert.ok(changed((workflow) => {
    workflow.jobs.verify_android_signed_smoke.steps[2].continue_on_error = true;
  }).some((message) => message.includes('without a bypass')));
});

test('rejects submission, approval, test-build, and toolchain graph weakening', () => {
  assert.ok(changed((workflow) => {
    workflow.jobs.submit_android.needs = ['build_android'];
  }).some((message) => message.includes('exact human-approved')));

  assert.ok(changed((workflow) => {
    workflow.jobs.test_android_signed_public.params.build_id = 'unverified-build';
  }).some((message) => message.includes('exact verified signed production APK')));

  assert.ok(changed((workflow) => {
    workflow.defaults.image = 'latest';
  }).some((message) => message.includes('pin the reviewed SDK 57 image')));
});

test('rejects weakening or bypassing the coordinator attendance acceptance gate', () => {
  assert.ok(changed((workflow) => {
    workflow.jobs.build_android_signed_smoke.needs = workflow.jobs.build_android_signed_smoke.needs
      .filter((jobId) => jobId !== 'test_android_attendance');
  }).some((message) => message.includes('every synthetic functional gate')));

  assert.ok(changed((workflow) => {
    workflow.jobs.test_android_attendance.params.flow_path = '.maestro/release-hermes-auth-smoke.yml';
  }).some((message) => message.includes('privacy-safe Android Maestro gate')));

  assert.ok(changed((workflow) => {
    workflow.jobs.test_android_attendance.params.record_screen = true;
  }).some((message) => message.includes('privacy-safe Android Maestro gate')));

  assert.ok(changed((workflow) => {
    workflow.jobs.test_android_attendance.params.build_id = '${{ needs.build_android_signed_smoke.outputs.build_id }}';
  }).some((message) => message.includes('exact smoke build')));

  assert.ok(changed((workflow) => {
    workflow.jobs.test_android_signed_public.params.flow_path =
      '.maestro/flows/coordinator-attendance-offline-android.yml';
  }).some((message) => message.includes('credential-free public shell')));
});
