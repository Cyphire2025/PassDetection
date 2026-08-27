import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { parseDocument } from 'yaml';

const require = createRequire(import.meta.url);
const {
  validateAndroidGradleWrapperPluginSource,
  validateAndroidLocalReleaseScripts,
  validateAttendanceFixtureBuildProfiles,
  validateProductionReleaseWorkflow,
} = require('./validate-maestro-workspace.js');
const workflowSource = readFileSync(
  new URL('../.eas/workflows/production-release.yml', import.meta.url),
  'utf8',
);
const baseline = parseDocument(workflowSource).toJS();
const easBaseline = JSON.parse(readFileSync(new URL('../eas.json', import.meta.url), 'utf8'));
const packageBaseline = JSON.parse(
  readFileSync(new URL('../package.json', import.meta.url), 'utf8'),
);
const appConfigBaseline = readFileSync(
  new URL('../app.config.ts', import.meta.url),
  'utf8',
);

function changed(mutator) {
  const workflow = structuredClone(baseline);
  mutator(workflow);
  return validateProductionReleaseWorkflow(workflow);
}

function changedPackage(mutator) {
  const packageDocument = structuredClone(packageBaseline);
  mutator(packageDocument);
  return validateAndroidLocalReleaseScripts(packageDocument);
}

test('accepts the exact reviewed production release graph', () => {
  assert.deepEqual(validateProductionReleaseWorkflow(structuredClone(baseline)), []);
  assert.deepEqual(validateAttendanceFixtureBuildProfiles(structuredClone(easBaseline)), []);
  assert.deepEqual(validateAndroidGradleWrapperPluginSource(appConfigBaseline), []);
  assert.match(workflowSource, /workflow:run \.eas\/workflows\/production-release\.yml --ref <full-commit-sha>/);
  assert.doesNotMatch(
    workflowSource,
    /stage-android-apk|outputs\/android-staging|android:release-artifacts/,
  );
});

test('requires the Gradle wrapper integrity plugin during clean Android prebuild', () => {
  assert.ok(validateAndroidGradleWrapperPluginSource(
    appConfigBaseline.replace(
      '"./plugins/with-android-gradle-wrapper-integrity",',
      '',
    ),
  ).some((message) => message.includes('wrapper integrity plugin')));
  assert.ok(validateAndroidGradleWrapperPluginSource(
    `${appConfigBaseline}\n"./plugins/with-android-gradle-wrapper-integrity"`,
  ).some((message) => message.includes('wrapper integrity plugin')));
});

test('rejects artifact substitution and signer-verification bypasses', () => {
  assert.ok(changed((workflow) => {
    workflow.jobs.verify_android_bundle.steps[1].with.build_id = 'different-build';
  }).some((message) => message.includes('exact signed build')));

  assert.ok(changed((workflow) => {
    workflow.jobs.verify_android_bundle.steps.splice(3, 0, {
      run: 'node scripts/replace-verified-receipt.js',
    });
  }).some((message) => message.includes('exact signed build')));

  assert.ok(changed((workflow) => {
    workflow.jobs.build_android.needs = workflow.jobs.build_android.needs
      .filter((jobId) => jobId !== 'verify_android_signed_smoke');
  }).some((message) => message.includes('mandatory Android gate')));

  assert.ok(changed((workflow) => {
    workflow.jobs.verify_android_signed_smoke.steps[2].continue_on_error = true;
  }).some((message) => message.includes('without a bypass')));

  assert.ok(changed((workflow) => {
    workflow.jobs.verify_android_signed_smoke.steps[2].run =
      workflow.jobs.verify_android_signed_smoke.steps[2].run.replace('x86_64', 'arm64-v8a');
  }).some((message) => message.includes('exact signed build')));

  assert.ok(changed((workflow) => {
    workflow.jobs.verify_android_signed_smoke.steps[2].run += ' surplus';
  }).some((message) => message.includes('exact signed build')));

  assert.ok(changed((workflow) => {
    workflow.jobs.verify_android_signed_smoke.env.GC_VERIFY_BUILD_ID =
      '11111111-1111-4111-8111-111111111111';
  }).some((message) => message.includes('exact signed build')));

  assert.ok(changed((workflow) => {
    delete workflow.jobs.verify_android_bundle.env.GC_VERIFY_SOURCE_FINGERPRINT_HASH;
  }).some((message) => message.includes('exact signed build')));

  assert.ok(changed((workflow) => {
    workflow.jobs.verify_android_signed_smoke.steps[2].run =
      workflow.jobs.verify_android_signed_smoke.steps[2].run.replace('env -i', 'env');
  }).some((message) => message.includes('exact signed build')));

  assert.ok(changed((workflow) => {
    workflow.jobs.verify_android_bundle.env.SENTRY_AUTH_TOKEN = 'must-not-pass';
  }).some((message) => message.includes('exact signed build')));

  assert.ok(changed((workflow) => {
    workflow.jobs.verify_android_bundle.steps[2].run =
      workflow.jobs.verify_android_bundle.steps[2].run.replace(
        'A099CFA1543F55593BC2ED16A70A7C67FE54B1747BB7301F37FDFD6D91028E29',
        '0'.repeat(64),
      );
  }).some((message) => message.includes('exact signed build')));
});

test('rejects production release profiles that permit uncommitted source', () => {
  const configuration = structuredClone(easBaseline);
  delete configuration.cli.requireCommit;
  assert.ok(
    validateAttendanceFixtureBuildProfiles(configuration)
      .some((message) => message.includes('clean committed source state')),
  );
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

test('rejects loss or substitution of lane-specific APK staging and re-verification', () => {
  assert.deepEqual(validateAndroidLocalReleaseScripts(structuredClone(packageBaseline)), []);

  assert.ok(changedPackage((packageDocument) => {
    packageDocument.scripts['android:gradle:apk:arm64:chain'] =
      packageDocument.scripts['android:gradle:apk:arm64:chain']
        .split(' && node scripts/stage-android-apk.js')[0];
  }).some((message) => message.includes('preserve NODE_ENV=production')));

  assert.ok(changedPackage((packageDocument) => {
    packageDocument.scripts['android:gradle:apk:arm64:chain'] =
      packageDocument.scripts['android:gradle:apk:arm64:chain'].replace(
        'outputs/android-staging/app-release-arm64-v8a.apk',
        'android/app/build/outputs/apk/release/staged/app-release-arm64-v8a.apk',
      );
  }).some((message) => message.includes('outside disposable Gradle build outputs')));

  assert.ok(changedPackage((packageDocument) => {
    packageDocument.scripts['android:gradle:apk:arm64:chain'] =
      packageDocument.scripts['android:gradle:apk:arm64:chain']
        .replace('"-PreactNativeArchitectures=arm64-v8a"', 'ORG_GRADLE_PROJECT_reactNativeArchitectures=arm64-v8a');
  }).some((message) => message.includes('preserve NODE_ENV=production')));

  assert.ok(changedPackage((packageDocument) => {
    packageDocument.scripts['android:gradle:apk:arm64'] =
      'npm run android:gradle:apk:arm64:chain';
  }).some((message) => message.includes('preserve NODE_ENV=production')));

  assert.ok(changedPackage((packageDocument) => {
    packageDocument.scripts['release:package-local-android-bundle'] =
      'node scripts/package-local-android-bundle.js';
  }).some((message) => message.includes('preserve NODE_ENV=production')));

  assert.ok(changedPackage((packageDocument) => {
    delete packageDocument.scripts['release:package-local-android-bundle'];
  }).some((message) => message.includes('preserve NODE_ENV=production')));

  assert.ok(changedPackage((packageDocument) => {
    packageDocument.scripts['release:verify-android-size'] =
      'node scripts/verify-android-binary-size.mjs android/app/build/outputs/apk/release/app-release.apk android/app/build/outputs/bundle/release/app-release.aab';
  }).some((message) => message.includes('preserve NODE_ENV=production')));

  assert.ok(changedPackage((packageDocument) => {
    packageDocument.scripts['android:release-artifacts'] =
      packageDocument.scripts['android:release-artifacts']
        .replace(' && npm run release:verify-staged-android-apk:arm64', '');
  }).some((message) => message.includes('preserve NODE_ENV=production')));
});

test('requires cmd-compatible Windows Gradle wrapper paths in local release chains', () => {
  assert.ok(changedPackage((packageDocument) => {
    packageDocument.scripts['android:gradle:apk:arm64:chain'] =
      packageDocument.scripts['android:gradle:apk:arm64:chain'].replace(
        'android\\gradlew.bat',
        'android/gradlew.bat',
      );
  }).some((message) => message.includes('preserve NODE_ENV=production')));

  assert.ok(changedPackage((packageDocument) => {
    packageDocument.scripts['android:gradle:apk:emulator:chain'] =
      packageDocument.scripts['android:gradle:apk:emulator:chain'].replace(
        'android\\gradlew.bat',
        'android/gradlew.bat',
      );
  }).some((message) => message.includes('preserve NODE_ENV=production')));

  assert.ok(changedPackage((packageDocument) => {
    packageDocument.scripts['android:gradle:aab'] =
      packageDocument.scripts['android:gradle:aab'].replace(
        'android\\gradlew.bat',
        'android/gradlew.bat',
      );
  }).some((message) => message.includes('preserve NODE_ENV=production')));
});
